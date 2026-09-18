# test_casparser.py

import casparser


PDF_PATH = r"C:\Users\USER\Downloads\AUG2026_AA43304075_TXN.pdf"
PDF_PASSWORD = "KTFPK7445P"


parsed_data = casparser.read_cas_pdf(
    PDF_PATH,
    PDF_PASSWORD,
    output="json",
)

print(parsed_data)

