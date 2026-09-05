# tools/melee-agent/tests/backtest/test_corpus_enumerate.py
from src.backtest.corpus import find_match_commit, parent_sha, commit_author_is_us


def make_runner(responses):
    def run(args):
        key = " ".join(args)
        for prefix, out in responses.items():
            if key.startswith(prefix):
                return out
        raise AssertionError(f"unexpected git call: {key}")
    return run


def test_find_match_commit_returns_newest():
    run = make_runner({"log --pretty=%H -S grIceMt_801F9ACC": "3ce0722cd\n0badc0de1\n"})
    assert find_match_commit(run, "grIceMt_801F9ACC", "src/melee/gr/gricemt.c") == "3ce0722cd"


def test_find_match_commit_none_when_empty():
    run = make_runner({"log --pretty=%H -S grIceMt_801F9ACC": "\n"})
    assert find_match_commit(run, "grIceMt_801F9ACC", "src/melee/gr/gricemt.c") is None


def test_parent_and_author():
    run = make_runner({"rev-parse 3ce0722cd~1": "13ccea114\n", "log -1 --pretty=%an 3ce0722cd": "Some Contributor\n"})
    assert parent_sha(run, "3ce0722cd") == "13ccea114"
    assert commit_author_is_us(run, "3ce0722cd", me="itsgrimetime") is False
