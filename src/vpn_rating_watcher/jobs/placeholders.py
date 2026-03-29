import typer


def not_implemented(job_name: str) -> None:
    typer.echo(f"[phase-1 placeholder] '{job_name}' is not implemented yet.")
