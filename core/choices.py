ACCOUNT_TYPE = (('C1', 'Client'),('C2','Admin'),('C3', 'Analyst') )


PLAN_CHOICES = [
    ("DIRECT", "Direct"),
    ("REGULAR", "Regular"),
]


OPTION_CHOICES = [
    ("GROWTH", "Growth"),
    ("IDCW", "IDCW"),
    ("IDCW_PAYOUT", "IDCW Payout"),
    ("IDCW_REINVESTMENT", "IDCW Reinvestment"),
]

FUND_TYPE_CHOICES = [
    ("OPEN_ENDED", "Open Ended Scheme"),
    ("CLOSE_ENDED", "Close Ended Scheme"),
    ("INTERVAL", "Interval"),
]

SCHEME_RISK_CHOICES = [
    ("LOW", "Low"),
    ("LOW_TO_MODERATE", "Low to Moderate"),
    ("MODERATE", "Moderate"),
    ("MODERATELY_HIGH", "Moderately High"),
    ("HIGH", "High"),
    ("VERY_HIGH", "Very High"),
]

RTA_AGENT_CHOICES = [
    ("CAMS", "CAMS"),
    ("KARVY", "Karvy"),

]

OTP_TYPE_CHOICES = [
    ("SIGNUP","SIGNUP"),
    ("LOGIN","login"),
    ("FORGOT_PASSWORD","forgot password"),
    ("FORGOT_USERNAME","forgot username"),
    ("RESET_PASSWORD","reset password"),
    ("RESET_USERNAME","reset username"),
]