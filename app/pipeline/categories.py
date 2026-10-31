"""
Maps the richer TransactionCategory enum onto the handoff's six top-level
category groups (TransactionCategoryGroup), and the COMMON_EXPENSE group
onto the spending subcategories the handoff's "Common expenses" section
asks for. See DECISIONS.md D-002.
"""
from app.models import TransactionCategory, TransactionCategoryGroup

CATEGORY_TO_GROUP = {
    TransactionCategory.INTERNAL_TRANSFER: TransactionCategoryGroup.INTERNAL_TRANSFER,
    TransactionCategory.SALARY: TransactionCategoryGroup.SALARY,
    TransactionCategory.BUSINESS_RECEIPT: TransactionCategoryGroup.BUSINESS_RECEIPT,
    TransactionCategory.POSSIBLE_BUSINESS_RECEIPT: TransactionCategoryGroup.BUSINESS_RECEIPT,
    TransactionCategory.REFUND: TransactionCategoryGroup.REFUND_REVERSAL,
    TransactionCategory.REVERSAL: TransactionCategoryGroup.REFUND_REVERSAL,
    TransactionCategory.LOAN_EMI: TransactionCategoryGroup.LOAN_EMI,
    TransactionCategory.RENT: TransactionCategoryGroup.COMMON_EXPENSE,
    TransactionCategory.UTILITIES: TransactionCategoryGroup.COMMON_EXPENSE,
    TransactionCategory.CARD_PAYMENT: TransactionCategoryGroup.COMMON_EXPENSE,
    TransactionCategory.OTHER_EXPENSE: TransactionCategoryGroup.COMMON_EXPENSE,
    TransactionCategory.CASH_DEPOSIT: TransactionCategoryGroup.COMMON_EXPENSE,
    TransactionCategory.CASH_WITHDRAWAL: TransactionCategoryGroup.COMMON_EXPENSE,
    TransactionCategory.BANK_CHARGES: TransactionCategoryGroup.COMMON_EXPENSE,
    TransactionCategory.INTEREST: TransactionCategoryGroup.COMMON_EXPENSE,
    TransactionCategory.LOAN_DISBURSEMENT: TransactionCategoryGroup.OTHER,
    TransactionCategory.UNVERIFIED_CREDIT: TransactionCategoryGroup.OTHER,
    TransactionCategory.RETURNED_PAYMENT: TransactionCategoryGroup.OTHER,
    TransactionCategory.UNCLASSIFIED: TransactionCategoryGroup.OTHER,
}


def group_of(category) -> TransactionCategoryGroup:
    if category is None:
        return TransactionCategoryGroup.OTHER
    return CATEGORY_TO_GROUP.get(category, TransactionCategoryGroup.OTHER)


# Discretionary vs essential, used by the Discretionary Spending Ratio and
# by spending-pattern behavioural analysis. A category/subcategory not
# listed here is left "unclassified" rather than forced into either bucket
# (handoff: "Keep unknown expenses unclassified rather than forcing a category").
DISCRETIONARY_SUBCATEGORIES = {
    "dining", "entertainment", "shopping", "travel", "subscriptions",
}
ESSENTIAL_SUBCATEGORIES = {
    "groceries", "transport", "healthcare", "insurance", "education",
}
# RENT and UTILITIES are already their own TransactionCategory (not routed
# through subcategory) and are always treated as essential/fixed.
ESSENTIAL_CATEGORIES = {
    TransactionCategory.RENT,
    TransactionCategory.UTILITIES,
    TransactionCategory.LOAN_EMI,
    TransactionCategory.BANK_CHARGES,
}

# Keyword lists for OTHER_EXPENSE subcategory classification. Ordered;
# first match wins. Anything matching none stays subcategory=None
# ("other_expense", unclassified) rather than being forced into a bucket.
SUBCATEGORY_KEYWORDS = [
    ("groceries", ["BIGBASKET", "GROFERS", "BLINKIT", "ZEPTO", "DMART", "GROCERY", "SUPERMARKET", "RELIANCEFRESH", "MORE SUPERMARKET"]),
    ("dining", ["SWIGGY", "ZOMATO", "RESTAURANT", "CAFE", "DINING", "FOODPANDA", "DOMINOS", "PIZZA", "STARBUCKS"]),
    ("entertainment", ["NETFLIX", "PRIMEVIDEO", "HOTSTAR", "SPOTIFY", "BOOKMYSHOW", "PVR", "INOX", "CINEMA", "MOVIE"]),
    ("transport", ["UBER", "OLA", "RAPIDO", "IRCTC", "INDIGO", "SPICEJET", "PETROL", "FUEL", "METRO", "FASTAG"]),
    ("healthcare", ["HOSPITAL", "PHARMACY", "APOLLO", "CLINIC", "DIAGNOSTIC", "MEDPLUS", "1MG", "PHARMEASY", "DOCTOR"]),
    ("insurance", ["INSURANCE", "LIC", "POLICY", "PREMIUM"]),
    ("education", ["SCHOOL", "COLLEGE", "TUITION", "UNIVERSITY", "COURSERA", "UDEMY", "EDUCATION"]),
    ("shopping", ["AMAZON", "FLIPKART", "MYNTRA", "AJIO", "SHOPPING", "MALL"]),
    ("subscriptions", ["SUBSCRIPTION", "MEMBERSHIP", "ICLOUD", "GOOGLEONE", "APPLE.COM"]),
]


def classify_expense_subcategory(description_norm: str) -> str | None:
    """Best-effort keyword subcategory for an OTHER_EXPENSE debit. None = unclassified."""
    for subcat, keywords in SUBCATEGORY_KEYWORDS:
        if any(kw.replace(" ", "") in description_norm for kw in keywords):
            return subcat
    return None


def is_discretionary(category: TransactionCategory, subcategory: str | None) -> bool | None:
    """
    True = discretionary, False = essential/fixed, None = unknown (kept out
    of both buckets rather than guessed - handoff instruction for the
    Discretionary Spending Ratio).
    """
    if category in ESSENTIAL_CATEGORIES:
        return False
    if category != TransactionCategory.OTHER_EXPENSE:
        return None
    if subcategory in DISCRETIONARY_SUBCATEGORIES:
        return True
    if subcategory in ESSENTIAL_SUBCATEGORIES:
        return False
    return None
