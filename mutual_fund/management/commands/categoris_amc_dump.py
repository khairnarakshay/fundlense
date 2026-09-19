import logging
import requests
from django.core.management.base import BaseCommand
from django.db import transaction

# Adjust these imports to match your actual Django app name
from mutual_fund.models import FundCategory, FundSubCategory, MutualFundAMC

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Seeds standardized SEBI categories and loads active AMFI AMC names in one unified process."

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("🔄 Initializing Mutual Fund Core Master Data Sync Engine..."))

        try:
            # Wrap all database modifications in a single atomic transaction block
            with transaction.atomic():

                # --- STEP 1: SEED SEBI CATEGORIES AND SUBCATEGORIES ---
                self.stdout.write("📦 Seeding standardized SEBI category architecture...")

                sebi_matrix = {
                    "Equity Schemes": [
                        "Multi Cap Fund", "Large Cap Fund", "Large & Mid Cap Fund",
                        "Mid Cap Fund", "Small Cap Fund", "Dividend Yield Fund",
                        "Value Fund", "Contra Fund", "Focused Fund",
                        "Sectoral/Thematic Fund", "ELSS", "Flexi Cap Fund"
                    ],
                    "Debt Schemes": [
                        "Overnight Fund", "Liquid Fund", "Ultra Short Duration Fund",
                        "Low Duration Fund", "Money Market Fund", "Short Duration Fund",
                        "Medium Duration Fund", "Medium to Long Duration Fund",
                        "Long Duration Fund", "Dynamic Bond Fund", "Corporate Bond Fund",
                        "Credit Risk Fund", "Banking and PSU Fund", "Gilt Fund",
                        "Gilt Fund with 10 year constant duration", "Floater Fund"
                    ],
                    "Hybrid Schemes": [
                        "Conservative Hybrid Fund", "Balanced Hybrid Fund", "Aggressive Hybrid Fund",
                        "Dynamic Asset Allocation/Balanced Advantage Fund", "Arbitrage Fund",
                        "Equity Savings Fund", "Multi Asset Allocation Fund"
                    ],
                    "Solution Oriented Schemes": [
                        "Retirement Fund", "Childrens Fund"
                    ],
                    "Other Schemes": [
                        "Index Funds", "Gold ETF", "Other ETFs", "Fund of Funds Domestic"
                    ]
                }

                for cat_name, subcategories in sebi_matrix.items():
                    category, _ = FundCategory.objects.get_or_create(
                        name=cat_name,
                        defaults={"description": f"Standardized SEBI mandated {cat_name} layer."}
                    )
                    for sub_name in subcategories:
                        FundSubCategory.objects.get_or_create(
                            category=category,
                            name=sub_name,
                            defaults={"description": f"SEBI rules mapping for {sub_name}."}
                        )

                self.stdout.write(self.style.SUCCESS("✅ Categories and Subcategories seeded successfully."))

                # --- STEP 2: EXTRACT AND DUMP AMC NAMES FROM AMFI ---
                self.stdout.write("🌐 Connecting to AMFI Repository to extract AMC names...")
                url = "https://amfiindia.com"
                response = requests.get(url, timeout=30)

                if response.status_code != 200:
                    raise Exception("Unable to reach AMFI server repository endpoint.")

                amc_names = set()

                # Process line by line using your exact extraction logic
                for line in response.text.split('\n'):
                    cleaned_line = line.strip()

                    # AMFI marks an AMC section using lines that end with 'Mutual Fund' or 'Asset Management'
                    if cleaned_line and (cleaned_line.endswith("Mutual Fund") or "Asset Management" in cleaned_line):
                        # Ignore operational row headers or specific subcategories
                        if ";" not in cleaned_line and "Open-Ended" not in cleaned_line and "Close-Ended" not in cleaned_line:
                            amc_names.add(cleaned_line)

                # Sort alphabetically
                sorted_amcs = sorted(list(amc_names))
                self.stdout.write(f"🏭 Total AMCs accurately identified: {len(sorted_amcs)}. Syncing with database...")

                new_amcs_count = 0
                for amc_name in sorted_amcs:
                    # update_or_create prevents IntegrityErrors on unique constraints
                    amc, created = MutualFundAMC.objects.update_or_create(
                        name=amc_name,
                        defaults={
                            "is_active": True
                        }
                    )
                    if created:
                        new_amcs_count += 1
                        self.stdout.write(f"   ➕ Created Record: {amc_name}")

                self.stdout.write(self.style.SUCCESS(
                    f"✅ Successfully processed {len(sorted_amcs)} AMCs ({new_amcs_count} new records added)."))

            self.stdout.write(self.style.SUCCESS("🎉 Unified Master Seeding Complete!"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Execution failed and database rolled back: {str(e)}"))
