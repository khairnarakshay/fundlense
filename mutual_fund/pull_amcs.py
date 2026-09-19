import requests

# Fetch the raw, comprehensive daily text data straight from AMFI
url = "https://www.amfiindia.com/spages/NAVAll.txt"
response = requests.get(url)

amc_names = set()

# Process line by line to extract the clean header divisions
for line in response.text.split('\n'):
    cleaned_line = line.strip()

    # AMFI marks an AMC section using lines that end with 'Mutual Fund' or 'Asset Management'
    if cleaned_line and (cleaned_line.endswith("Mutual Fund") or "Asset Management" in cleaned_line):
        # Ignore operational row headers or specific subcategories
        if ";" not in cleaned_line and "Open-Ended" not in cleaned_line and "Close-Ended" not in cleaned_line:
            amc_names.add(cleaned_line)

# Sort alphabetically and print everything
sorted_amcs = sorted(list(amc_names))
print(f"Total AMCs accurately identified: {len(sorted_amcs)}\n")

for index, amc in enumerate(sorted_amcs, start=1):
    print(f"{index}. {amc}")
