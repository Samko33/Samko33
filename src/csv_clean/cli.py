"""Command line interface for the csv-clean tool."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .processing import (
    CSVRuntimeError,
    CSVValidationError,
    ProcessingConfig,
    apply_normalization,
    find_potential_duplicates,
    prepare_output_frames,
    read_input_csv,
    remove_exact_duplicates,
    validate_columns,
)

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=True)


def _print_verbose(message: str, *, verbosity: int, level: int = 1) -> None:
    """Print helper that respects the verbosity level."""

    if verbosity >= level:
        console.print(message)


def run_pipeline(
    *,
    input_path: Path,
    output_dir: Path,
    email_col: str,
    name_col: str,
    city_col: str,
    phone_col: str,
    threshold: float,
    max_rows: Optional[int],
    separator: str,
    dry_run: bool,
    verbose: int,
) -> None:
    """Execute the deduplication workflow."""

    start_time = time.perf_counter()

    if not input_path.exists():
        console.print(f"[red]Input file not found:[/red] {input_path}")
        raise typer.Exit(code=2)

    _print_verbose("Reading input CSV...", verbosity=verbose)

    try:
        df = read_input_csv(input_path, separator=separator, max_rows=max_rows)
    except FileNotFoundError as exc:
        console.print(f"[red]Input file not found:[/red] {input_path}")
        raise typer.Exit(code=2) from exc
    except CSVValidationError as exc:
        console.print(f"[red]Validation error:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        console.print(f"[red]Unexpected error while reading CSV:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    config = ProcessingConfig(
        email_col=email_col,
        name_col=name_col,
        city_col=city_col,
        phone_col=phone_col,
        original_columns=list(df.columns),
    )

    try:
        validate_columns(df, config)
    except CSVValidationError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    if not config.has_name():
        name_warning = (
            f"[yellow]Column '{name_col}' missing; name fuzzy match skipped.[/yellow]"
        )
        console.print(name_warning)
    if not config.has_city():
        city_warning = (
            f"[yellow]Column '{city_col}' missing; city fuzzy match skipped.[/yellow]"
        )
        console.print(city_warning)

    _print_verbose("Normalizing records...", verbosity=verbose)

    try:
        normalized_df, review_records = apply_normalization(df, config)
    except CSVRuntimeError as exc:  # pragma: no cover - defensive
        console.print(f"[red]Runtime error:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    invalid_count = len(review_records)
    if invalid_count:
        email_warning = (
            f"[yellow]{invalid_count} row(s) flagged for email review.[/yellow]"
        )
        console.print(email_warning)

    _print_verbose("Removing exact duplicates...", verbosity=verbose)
    clean_df, duplicates_df = remove_exact_duplicates(normalized_df)

    duplicate_summary = (
        f"[green]{len(clean_df)}[/green] clean row(s); "
        f"[cyan]{len(duplicates_df)}[/cyan] exact duplicate(s) removed."
    )
    console.print(duplicate_summary)

    if config.has_name() and config.has_city():
        _print_verbose("Running fuzzy matching...", verbosity=verbose)
        fuzzy_records = find_potential_duplicates(clean_df, config, threshold=threshold)
        review_records.extend(fuzzy_records)
        fuzzy_summary = (
            f"[magenta]{len(fuzzy_records)}[/magenta] potential duplicate pair(s) "
            "added for review."
        )
        console.print(fuzzy_summary)
    else:
        console.print(
            "[yellow]Fuzzy matching skipped; missing name or city column.[/yellow]"
        )

    clean_output, duplicates_output, review_output = prepare_output_frames(
        clean_df, duplicates_df, review_records, config
    )

    if dry_run:
        console.print("[cyan]Dry-run enabled; no files were written.[/cyan]")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        clean_output.to_csv(output_dir / "clean.csv", index=False, sep=separator)
        duplicates_output.to_csv(
            output_dir / "duplicates.csv", index=False, sep=separator
        )
        review_output.to_csv(output_dir / "review.csv", index=False, sep=separator)
        console.print(f"[green]Results written to {output_dir.resolve()}[/green]")

    elapsed = time.perf_counter() - start_time
    summary = Table(title="Summary", show_header=True, header_style="bold blue")
    summary.add_column("File")
    summary.add_column("Rows", justify="right")
    summary.add_row("clean.csv", str(len(clean_output)))
    summary.add_row("duplicates.csv", str(len(duplicates_output)))
    summary.add_row("review.csv", str(len(review_output)))
    console.print(summary)
    console.print(f"Completed in {elapsed:0.2f} seconds.")


@app.callback(invoke_without_command=True)
def main(  # noqa: B008
    ctx: typer.Context,
    input: Path = typer.Option(..., "--input", help="Path to the input CSV file."),
    output_dir: Path = typer.Option(
        Path("out"), "--output-dir", help="Where to write the output CSV files."
    ),
    email_col: str = typer.Option("email", help="Name of the email column."),
    name_col: str = typer.Option("name", help="Name column used for fuzzy matching."),
    city_col: str = typer.Option("city", help="City column used for fuzzy matching."),
    phone_col: str = typer.Option(
        "phone",
        help="Phone column (optional normalization).",
    ),
    threshold: float = typer.Option(
        0.85,
        min=0.6,
        max=0.95,
        help="Fuzzy matching threshold between 0.6 and 0.95.",
    ),
    max_rows: Optional[int] = typer.Option(
        None, help="Optional safety limit for number of rows to read."
    ),
    separator: str = typer.Option(",", help="Field separator used in the CSV."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--no-dry-run",
        help="Run the pipeline without writing any files.",
    ),
    verbose: int = typer.Option(
        0, "--verbose", "-v", count=True, help="Increase logging verbosity."
    ),
    version: bool = typer.Option(
        False,
        "--version",
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Typer callback that dispatches to the processing pipeline."""

    if version:
        console.print(f"csv-clean version {__version__}")
        raise typer.Exit()

    if ctx.invoked_subcommand is not None:
        return

    run_pipeline(
        input_path=input,
        output_dir=output_dir,
        email_col=email_col,
        name_col=name_col,
        city_col=city_col,
        phone_col=phone_col,
        threshold=threshold,
        max_rows=max_rows,
        separator=separator,
        dry_run=dry_run,
        verbose=verbose,
    )


def entrypoint() -> None:
    """Entrypoint for console script."""

    app()


if __name__ == "__main__":  # pragma: no cover - script entry
    entrypoint()
