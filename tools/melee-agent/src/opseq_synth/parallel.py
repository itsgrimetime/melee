"""
Parallel compilation for opseq synthesis.

Uses multiprocessing to compile many snippets concurrently.
"""

import multiprocessing as mp
import time
from dataclasses import dataclass
from multiprocessing import Process, Queue
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .compiler import Compiler, CompileResult
from .contexts import ALL_CONTEXTS, ContextGenerator, MinimalContext
from .storage import OpcodeDB
from .templates import ALL_TEMPLATES, Template


@dataclass
class CompileTask:
    """A compilation task for a worker."""

    snippet: str
    template_name: str
    context_name: str


@dataclass
class CompileOutput:
    """Result from a worker."""

    success: bool
    snippet: str
    template_name: str
    context_name: str
    mnemonics: list[str] | None
    normalized: list[str] | None
    error: str | None


def worker_process(
    task_queue: Queue,
    result_queue: Queue,
    melee_root: Path,
):
    """Worker process that compiles snippets."""
    compiler = Compiler(melee_root)
    contexts = {ctx.name: ctx for ctx in ALL_CONTEXTS}

    while True:
        task = task_queue.get()
        if task is None:  # Poison pill
            break

        context = contexts.get(task.context_name, MinimalContext())
        result = compiler.compile_snippet(
            task.snippet,
            context,
            template_name=task.template_name,
        )

        output = CompileOutput(
            success=result.success,
            snippet=task.snippet,
            template_name=task.template_name,
            context_name=task.context_name,
            mnemonics=result.opcodes.mnemonics if result.opcodes else None,
            normalized=result.opcodes.normalized if result.opcodes else None,
            error=result.error,
        )
        result_queue.put(output)


def generate_tasks(
    templates: list[Template],
    contexts: list[ContextGenerator],
    max_expansions_per_template: int = 10,
) -> Iterator[CompileTask]:
    """Generate compilation tasks from templates and contexts."""
    for template in templates:
        expansions = template.expand()[:max_expansions_per_template]
        for snippet in expansions:
            for context in contexts:
                yield CompileTask(
                    snippet=snippet,
                    template_name=template.name,
                    context_name=context.name,
                )


class ParallelCompiler:
    """
    Parallel compilation manager.

    Usage:
        pc = ParallelCompiler(num_workers=4)
        pc.start()

        for task in generate_tasks(templates, contexts):
            pc.submit(task)

        for result in pc.collect():
            if result.success:
                db.insert(...)

        pc.stop()
    """

    def __init__(self, num_workers: int = 4, melee_root: Path | None = None):
        self.num_workers = num_workers
        self.melee_root = melee_root or Path(__file__).parents[2] / "melee"

        self.task_queue: Queue = Queue()
        self.result_queue: Queue = Queue()
        self.workers: list[Process] = []
        self.tasks_submitted = 0
        self.results_collected = 0

    def start(self):
        """Start worker processes."""
        for _ in range(self.num_workers):
            p = Process(
                target=worker_process,
                args=(self.task_queue, self.result_queue, self.melee_root),
            )
            p.start()
            self.workers.append(p)

    def submit(self, task: CompileTask):
        """Submit a task for compilation."""
        self.task_queue.put(task)
        self.tasks_submitted += 1

    def collect(self, timeout: float = 1.0) -> Iterator[CompileOutput]:
        """Collect results from workers."""
        while self.results_collected < self.tasks_submitted:
            try:
                result = self.result_queue.get(timeout=timeout)
                self.results_collected += 1
                yield result
            except:
                # Check if workers are still alive
                if not any(w.is_alive() for w in self.workers):
                    break

    def stop(self):
        """Stop all workers."""
        # Send poison pills
        for _ in self.workers:
            self.task_queue.put(None)

        # Wait for workers to finish
        for w in self.workers:
            w.join(timeout=5.0)
            if w.is_alive():
                w.terminate()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


def bulk_generate(
    db_path: Path,
    templates: list[Template] | None = None,
    contexts: list[ContextGenerator] | None = None,
    num_workers: int = 4,
    max_expansions: int = 10,
    progress_callback=None,
):
    """
    Bulk generate samples to a database using parallel compilation.

    Args:
        db_path: Path to SQLite database
        templates: Templates to use (default: ALL_TEMPLATES)
        contexts: Contexts to use (default: [MinimalContext])
        num_workers: Number of parallel workers
        max_expansions: Max expansions per template
        progress_callback: Optional callback(stored, failed, elapsed)
    """
    templates = templates or ALL_TEMPLATES
    contexts = contexts or [MinimalContext()]

    db = OpcodeDB(db_path)
    stored = 0
    failed = 0
    start_time = time.time()

    with ParallelCompiler(num_workers=num_workers) as pc:
        # Submit all tasks
        tasks = list(generate_tasks(templates, contexts, max_expansions))
        for task in tasks:
            pc.submit(task)

        print(f"Submitted {len(tasks)} tasks to {num_workers} workers...")

        # Collect results
        for result in pc.collect():
            if result.success and result.mnemonics:
                from .opcodes import OpcodeSequence

                opcodes = OpcodeSequence(
                    raw=result.mnemonics,
                    mnemonics=result.mnemonics,
                    normalized=result.normalized or result.mnemonics,
                )
                db.insert_sample(
                    source=result.snippet,
                    opcodes=opcodes,
                    template_name=result.template_name,
                    context_name=result.context_name,
                )
                stored += 1
            else:
                failed += 1

            # Progress callback
            if progress_callback and (stored + failed) % 10 == 0:
                elapsed = time.time() - start_time
                progress_callback(stored, failed, elapsed)

    db.close()

    elapsed = time.time() - start_time
    rate = (stored + failed) / elapsed if elapsed > 0 else 0
    print(f"Done: {stored} stored, {failed} failed in {elapsed:.1f}s ({rate:.1f}/sec)")

    return stored, failed
