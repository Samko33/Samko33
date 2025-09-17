# csv-clean

Command-line CSV and Google-Sheets style deduplication that runs entirely on your laptop.

## Why csv-clean?
- ✅ Remove exact duplicates by email in seconds.
- 🔍 Spot likely duplicates based on fuzzy matching of `name + city`.
- 📦 Export three ready-to-share files: `clean.csv`, `duplicates.csv`, and `review.csv`.
- 🧰 Batteries-included: sample data, tests, formatting, and CI.

## Installation
The project targets Python 3.11. The easiest way to install is via [pipx](https://pipx.pypa.io/):

```bash
pipx install .
```

Alternatively, inside a virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

All runtime dependencies are listed in `pyproject.toml` and `requirements.txt`.

## Quickstart
Run the tool against the provided sample data:

```bash
csv-clean --input examples/customers_small.csv --output-dir out
```

Outputs (all written to `--output-dir` unless `--dry-run` is used):

- `clean.csv` – dataset with invalid emails removed and duplicates collapsed.
- `duplicates.csv` – entries dropped due to exact email duplication, including `source_index` and `kept_index` columns.
- `review.csv` – rows needing human review, including invalid emails and fuzzy matches with similarity scores.

Pass `--dry-run` to skip writing files while still seeing the summary.

## CLI options
```
Usage: csv-clean [OPTIONS]

Options:
  --input PATH                 Path to the input CSV file.  [required]
  --output-dir PATH            Where to write the output CSV files.  [default: out]
  --email-col TEXT             Name of the email column.  [default: email]
  --name-col TEXT              Name column used for fuzzy matching.  [default: name]
  --city-col TEXT              City column used for fuzzy matching.  [default: city]
  --phone-col TEXT             Phone column (optional normalization).  [default: phone]
  --threshold FLOAT RANGE      Fuzzy matching threshold between 0.6 and 0.95.  [default: 0.85]
  --max-rows INTEGER           Optional safety limit for number of rows to read.
  --separator TEXT             Field separator used in the CSV.  [default: ,]
  --dry-run / --no-dry-run     Run the pipeline without writing any files.
  -v, --verbose                Increase logging verbosity (use `-vv` for debug output).
  --version                    Show the version and exit.
  --help                       Show this message and exit.
```

### Custom column names
```
csv-clean \
  --input data/raw_contacts.csv \
  --email-col primaryEmail \
  --name-col fullName \
  --city-col hometown \
  --phone-col workPhone
```

### Different separators
```
csv-clean --input data/contacts.tsv --separator "\t"
```

### Limiting rows for a quick preview
```
csv-clean --input huge.csv --max-rows 5000 --dry-run -v
```

## Sample data
- `examples/customers_small.csv` – 15 records with deliberate exact duplicates, fuzzy matches, and invalid emails.
- `examples/customers_medium.csv` – 422 synthetic rows with many near-duplicates to benchmark performance.

## Development workflow
Useful `make` targets:

```bash
make venv     # create .venv and install dependencies
make test     # run pytest
make format   # run ruff --fix and black on the codebase
make run      # execute csv-clean against examples/customers_small.csv
```

## Performance notes
- `csv-clean` loads the CSV with `pandas`. For very large files, use `--max-rows` to sample or split the input.
- RapidFuzz comparisons are blocked by name initial and city to avoid quadratic blow-ups.
- All processing happens in-memory; ensure you have enough RAM for the dataset size.

## Privacy
No data ever leaves your machine. The tool performs all work locally and does not contact external services.

## Troubleshooting
| Issue | Fix |
| --- | --- |
| **File not found / permission error** | Double-check the `--input` path and ensure you have read access. |
| **Missing columns** | Use `--email-col`, `--name-col`, or `--city-col` to match your headers. The tool reports missing required columns and skips fuzzy matching if optional fields are absent. |
| **Bad encoding (UnicodeDecodeError)** | Convert the CSV to UTF-8 (e.g., using spreadsheet software) before running `csv-clean`. |
| **Strange characters or wrong separators** | Specify the separator with `--separator` (e.g., `;` or `\t`). |
| **Large file memory pressure** | Use `--max-rows` for sampling or split the data into smaller chunks. |

## Continuous integration
GitHub Actions runs `pytest` on every push to ensure the pipeline remains healthy.
