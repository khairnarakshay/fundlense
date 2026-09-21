"""Test the open-source casparser library with a CAS PDF."""

from pathlib import Path

import casparser


PDF_PATH = Path(r"C:\Users\khair\Downloads\KTXXXXXX5P_01012010-20092026_CP224924376_20092026105328600.pdf")
PDF_PASSWORD = "Password@123"
OUTPUT_DIR = Path(r"F:\fundlense\fundlense\cas_parser\services\CAS")


def save_output(file_name: str, content: str) -> None:
    """Save parser output to the output directory."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / file_name
    output_path.write_text(content, encoding="utf-8")
    print(f"Saved: {output_path}")


def main() -> None:
    """Parse the CAS PDF and save JSON and CSV outputs."""

    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF file not found: {PDF_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Parsing CAS PDF with casparser...")

    cas_data = casparser.read_cas_pdf(
        str(PDF_PATH),
        PDF_PASSWORD,
    )

    print("CAS parsing completed.")
    print(f"Parsed data type: {type(cas_data).__name__}")

    json_output = casparser.read_cas_pdf(
        str(PDF_PATH),
        PDF_PASSWORD,
        output="json",
    )

    save_output("casparser_output.json", json_output)

    csv_output = casparser.read_cas_pdf(
        str(PDF_PATH),
        PDF_PASSWORD,
        output="csv",
    )

    save_output("casparser_output.csv", csv_output)

    print("JSON and CSV output generated successfully.")


if __name__ == "__main__":
    main()