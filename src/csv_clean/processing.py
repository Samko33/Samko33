"""Core processing utilities for the csv-clean CLI."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd
from rapidfuzz import fuzz

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CSVValidationError(Exception):
    """Raised when the input data fails upfront validation."""


class CSVRuntimeError(Exception):
    """Raised when an unexpected runtime problem occurs."""


@dataclass(slots=True)
class ProcessingConfig:
    """Configuration for column names and contextual metadata."""

    email_col: str
    name_col: str
    city_col: str
    phone_col: str
    original_columns: List[str]

    def has_name(self) -> bool:
        return self.name_col in self.original_columns

    def has_city(self) -> bool:
        return self.city_col in self.original_columns

    def has_phone(self) -> bool:
        return self.phone_col in self.original_columns


def read_input_csv(
    path: Path,
    separator: str = ",",
    max_rows: int | None = None,
) -> pd.DataFrame:
    """Read a CSV file into a DataFrame with sensible defaults."""

    try:
        df = pd.read_csv(
            path,
            sep=separator,
            dtype=str,
            keep_default_na=False,
            nrows=max_rows,
        )
    except FileNotFoundError:  # pragma: no cover - handled by CLI
        raise
    except pd.errors.EmptyDataError as exc:
        raise CSVValidationError("The provided CSV file is empty.") from exc
    except UnicodeDecodeError as exc:
        message = (
            "Unable to decode the file using UTF-8. Check encoding or provide "
            "a different file."
        )
        raise CSVValidationError(message) from exc

    if df.empty:
        raise CSVValidationError("The provided CSV file contains no rows.")

    # Strip whitespace from column headers to avoid subtle mismatches.
    df.rename(columns={col: col.strip() for col in df.columns}, inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def validate_columns(df: pd.DataFrame, config: ProcessingConfig) -> None:
    """Ensure required columns exist before processing."""

    missing: List[str] = []
    if config.email_col not in df.columns:
        missing.append(config.email_col)

    if missing:
        missing_message = "Missing required column(s): " + ", ".join(
            sorted(set(missing))
        )
        raise CSVValidationError(missing_message)


def _normalize_email(value: Any) -> Tuple[str | None, str | None]:
    """Normalize email addresses and return potential issues."""

    if value is None:
        return None, "missing_email"

    text = str(value).strip()
    if not text:
        return None, "missing_email"

    lowered = text.lower()
    if not EMAIL_REGEX.match(lowered):
        return None, "invalid_email"

    return lowered, None


def _normalize_phone(value: Any) -> str:
    """Keep only digits from phone numbers."""

    if value is None:
        return ""
    return "".join(ch for ch in str(value) if ch.isdigit())


def _normalize_name(value: Any) -> str:
    """Normalize a name for matching purposes."""

    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text)
    return collapsed.title()


def _normalize_city(value: Any) -> str:
    """Normalize a city for matching purposes."""

    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    collapsed = re.sub(r"\s+", " ", text)
    return collapsed.title()


def _clean_value(value: Any) -> str:
    """Convert values to clean strings for CSV export."""

    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, str):
        return value
    if pd.isna(value):  # type: ignore[arg-type]
        return ""
    return str(value)


def _build_review_record(
    row: pd.Series,
    config: ProcessingConfig,
    *,
    reason: str,
    note: str = "",
    other_row: pd.Series | None = None,
    score: float | None = None,
) -> Dict[str, Any]:
    """Create a dictionary capturing review information for CSV export."""

    record: Dict[str, Any] = {
        "reason": reason,
        "score": round(score, 4) if score is not None else "",
        "row_index": int(row["_original_index"]),
        "note": note,
    }
    if other_row is not None:
        record["other_index"] = int(other_row["_original_index"])
    else:
        record["other_index"] = ""

    for col in config.original_columns:
        row_key = f"row_{col}"
        other_key = f"other_{col}"
        record[row_key] = _clean_value(row.get(col))
        other_value = other_row.get(col) if other_row is not None else ""
        record[other_key] = _clean_value(other_value)

    return record


def apply_normalization(
    df: pd.DataFrame, config: ProcessingConfig
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """Normalize key columns and return valid rows plus review records."""

    working = df.copy()
    working.reset_index(drop=True, inplace=True)
    working["_original_index"] = working.index

    # Normalize email values.
    email_results = working[config.email_col].apply(_normalize_email)
    working["_normalized_email"] = [result[0] for result in email_results]
    working["_email_issue"] = [result[1] for result in email_results]

    # Normalize optional fields if present.
    if config.has_phone():
        working["_normalized_phone"] = working[config.phone_col].apply(_normalize_phone)
    else:
        working["_normalized_phone"] = ""

    if config.has_name():
        working["_normalized_name"] = working[config.name_col].apply(_normalize_name)
    else:
        working["_normalized_name"] = ""

    if config.has_city():
        working["_normalized_city"] = working[config.city_col].apply(_normalize_city)
    else:
        working["_normalized_city"] = ""

    name_component = working["_normalized_name"].str.strip()
    city_component = working["_normalized_city"].str.strip()
    combined_key = name_component + " " + city_component
    working["_match_key"] = combined_key.str.strip().fillna("")

    review_records: List[Dict[str, Any]] = []
    issue_mask = working["_email_issue"].notna()
    if issue_mask.any():
        issue_rows = working.loc[issue_mask]
        for _, row in issue_rows.iterrows():
            reason = str(row["_email_issue"])
            if reason == "missing_email":
                note = "Missing or empty email address"
            else:
                note = "Invalid email format"
            review_records.append(
                _build_review_record(row, config, reason=reason, note=note)
            )
        working = working.loc[~issue_mask].copy()

    return working, review_records


def remove_exact_duplicates(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split exact email duplicates from the clean dataset."""

    if "_normalized_email" not in df.columns:
        raise CSVRuntimeError("Normalized email column missing from DataFrame.")

    duplicated_mask = df["_normalized_email"].duplicated(keep="first")
    duplicates = df.loc[duplicated_mask].copy()
    clean = df.loc[~duplicated_mask].copy()

    if not duplicates.empty:
        first_occurrence = clean.drop_duplicates(
            subset="_normalized_email", keep="first"
        ).set_index("_normalized_email")["_original_index"]
        duplicates["source_index"] = duplicates["_original_index"].astype(int)
        duplicates["kept_index"] = (
            duplicates["_normalized_email"].map(first_occurrence).astype(int)
        )
    else:
        duplicates["source_index"] = pd.Series(dtype=int)
        duplicates["kept_index"] = pd.Series(dtype=int)

    return clean, duplicates


def find_potential_duplicates(
    df: pd.DataFrame,
    config: ProcessingConfig,
    *,
    threshold: float,
) -> List[Dict[str, Any]]:
    """Identify likely duplicates via fuzzy matching on name and city."""

    if "_match_key" not in df.columns:
        return []

    threshold_score = max(0.0, min(1.0, threshold)) * 100
    records: List[Dict[str, Any]] = []

    # Prepare blocking to avoid O(n^2) comparisons.
    blocks: Dict[str, List[int]] = defaultdict(list)
    for idx, row in df.iterrows():
        match_key = row["_match_key"]
        if not isinstance(match_key, str) or not match_key:
            continue
        name_norm = row.get("_normalized_name", "")
        city_norm = row.get("_normalized_city", "")
        if isinstance(name_norm, str) and name_norm:
            blocks[f"name:{name_norm[0]}"].append(idx)
        if isinstance(city_norm, str) and city_norm:
            blocks[f"city:{city_norm}"].append(idx)

    seen_pairs: set[Tuple[int, int]] = set()

    for indices in blocks.values():
        if len(indices) < 2:
            continue
        unique_indices = sorted(set(indices))
        for left, right in combinations(unique_indices, 2):
            pair = (min(left, right), max(left, right))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            row_left = df.loc[left]
            row_right = df.loc[right]
            key_left = row_left["_match_key"]
            key_right = row_right["_match_key"]
            if not key_left or not key_right:
                continue
            score = fuzz.token_set_ratio(key_left, key_right)
            if score < threshold_score:
                continue
            normalized_score = round(score / 100.0, 4)
            note = f"Match key '{key_left}' vs '{key_right}'"
            records.append(
                _build_review_record(
                    row_left,
                    config,
                    reason="name+city",
                    note=note,
                    other_row=row_right,
                    score=normalized_score,
                )
            )

    return records


def prepare_output_frames(
    clean_df: pd.DataFrame,
    duplicates_df: pd.DataFrame,
    review_records: Sequence[Dict[str, Any]],
    config: ProcessingConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Prepare DataFrames ready for CSV export without helper columns."""

    helper_cols = [col for col in clean_df.columns if col.startswith("_")]

    clean_output = clean_df.drop(columns=helper_cols, errors="ignore")
    clean_output = clean_output[config.original_columns]

    duplicates_output = duplicates_df.drop(columns=helper_cols, errors="ignore")
    duplicates_output = duplicates_output[
        ["source_index", "kept_index", *config.original_columns]
    ]

    review_output = pd.DataFrame(list(review_records))
    if review_output.empty:
        base_cols = ["reason", "score", "row_index", "other_index", "note"]
        row_cols = [f"row_{col}" for col in config.original_columns]
        other_cols = [f"other_{col}" for col in config.original_columns]
        review_output = pd.DataFrame(columns=[*base_cols, *row_cols, *other_cols])

    return clean_output, duplicates_output, review_output
