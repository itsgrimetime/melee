"""PR commands - track functions through PR lifecycle."""

import typer

from .check import check_command
from .describe import describe_command
from .feedback import feedback_command
from .link import link_batch_command, link_command, unlink_command
from .status import list_command, status_command

pr_app = typer.Typer(help="Track functions through PR lifecycle")

# Register commands
pr_app.command("link")(link_command)
pr_app.command("link-batch")(link_batch_command)
pr_app.command("unlink")(unlink_command)
pr_app.command("status")(status_command)
pr_app.command("list")(list_command)
pr_app.command("check")(check_command)
pr_app.command("describe")(describe_command)
pr_app.command("feedback")(feedback_command)
