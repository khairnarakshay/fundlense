import logging
import requests
from django.core.management.base import BaseCommand
from django.db import transaction

# Adjust these imports to match your actual Django app name
from mutual_fund.models import FundCategory, FundSubCategory, MutualFundAMC
import re

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

                # --- STEP 2: EXTRACT AND DUMP AMC DATA FROM AMFI ---
                self.stdout.write("🌐 Connecting to AMFI to extract AMC master data...")

                from amfipy import AMFIClient

                client = AMFIClient()

                try:
                    filters = client.fund_performance.filters()
                    amc_list = filters.get("mutualFundList", [])
                except Exception as exc:
                    raise Exception(f"Unable to retrieve AMC master data from AMFI: {exc}")

                if not amc_list:
                    raise Exception(
                        "AMFI returned an empty AMC list. "
                        "No AMC records were modified."
                    )

                self.stdout.write(
                    f"🏭 Total AMCs received from AMFI: {len(amc_list)}. "
                    "Syncing with database..."
                )

                new_amcs_count = 0
                existing_amcs_count = 0

                for amc_data in amc_list:
                    amc_name = str(amc_data.get("name", "")).strip()
                    amfi_id = amc_data.get("id")

                    if not amc_name:
                        continue

                    amc, created = MutualFundAMC.objects.update_or_create(
                        name=amc_name,
                        defaults={
                            "is_active": True,
                        },
                    )

                    if created:
                        new_amcs_count += 1
                        self.stdout.write(
                            f"   ➕ Created AMC: {amc_name} "
                            f"(AMFI ID: {amfi_id})"
                        )
                    else:
                        existing_amcs_count += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ Successfully processed {len(amc_list)} AMCs "
                        f"({new_amcs_count} new, "
                        f"{existing_amcs_count} existing)."
                    )
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(e))