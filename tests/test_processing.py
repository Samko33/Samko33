from __future__ import annotations

import pandas as pd
import pytest
from csv_clean.cli import app
from csv_clean.processing import (
    CSVValidationError,
    ProcessingConfig,
    apply_normalization,
    find_potential_duplicates,
    prepare_output_frames,
    remove_exact_duplicates,
    validate_columns,
)
from typer.testing import CliRunner


def make_config(df: pd.DataFrame) -> ProcessingConfig:
    return ProcessingConfig(
        email_col="email",
        name_col="name",
        city_col="city",
        phone_col="phone",
        original_columns=list(df.columns),
    )


def test_exact_duplicate_removal() -> None:
    df = pd.DataFrame(
        {
            "email": ["alice@example.com", "ALICE@example.com", "bob@example.com"],
            "name": ["Alice Smith", "Alice Smith", "Bob Brown"],
            "city": ["Austin", "Austin", "Dallas"],
            "phone": ["111-222-3333", "111-222-3333", "555-111-0000"],
        }
    )

    config = make_config(df)
    normalized, review_records = apply_normalization(df, config)
    assert review_records == []

    clean_df, duplicates_df = remove_exact_duplicates(normalized)
    assert len(clean_df) == 2
    assert len(duplicates_df) == 1
    assert duplicates_df.iloc[0]["source_index"] == 1
    assert duplicates_df.iloc[0]["kept_index"] == 0

    clean_out, duplicates_out, review_out = prepare_output_frames(
        clean_df, duplicates_df, review_records, config
    )
    assert len(clean_out) == 2
    assert len(duplicates_out) == 1
    assert review_out.empty


def test_fuzzy_matching_threshold_behavior() -> None:
    df = pd.DataFrame(
        {
            "email": ["one@example.com", "two@example.com"],
            "name": ["Jonathon Doe", "Jonathan Doe"],
            "city": ["Springfield", "Springfield"],
            "phone": ["1234567890", "0987654321"],
        }
    )

    config = make_config(df)
    normalized, review_records = apply_normalization(df, config)
    assert not review_records

    clean_df, duplicates_df = remove_exact_duplicates(normalized)
    assert duplicates_df.empty

    matches = find_potential_duplicates(clean_df, config, threshold=0.8)
    assert len(matches) == 1
    assert matches[0]["reason"] == "name+city"

    strict_matches = find_potential_duplicates(clean_df, config, threshold=0.98)
    assert strict_matches == []


def test_missing_email_column_raises() -> None:
    df = pd.DataFrame({"name": ["Alice"], "city": ["Austin"]})
    config = ProcessingConfig(
        email_col="email",
        name_col="name",
        city_col="city",
        phone_col="phone",
        original_columns=list(df.columns),
    )

    with pytest.raises(CSVValidationError):
        validate_columns(df, config)


def test_cli_smoke(tmp_path) -> None:
    csv_path = tmp_path / "input.csv"
    csv_path.write_text(
        "email,name,city\n"
        "alice@example.com,Alice Smith,Austin\n"
        "bob@example.com,Bob Brown,Dallas\n"
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--input",
            str(csv_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.stdout
    output_text = result.stdout or result.stderr
    assert "Summary" in output_text
