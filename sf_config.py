"""Salesforce uploader configuration.

Before running, fill in the two sections below:
  1. .env file  – OAuth credentials
  2. SF_FIELD_MAP – Excel field name → Salesforce field API name
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Salesforce Connected App credentials  (set in .env)
# ---------------------------------------------------------------------------
SF_USERNAME       = os.getenv("SF_USERNAME", "")
SF_PASSWORD       = os.getenv("SF_PASSWORD", "")
SF_SECURITY_TOKEN = os.getenv("SF_SECURITY_TOKEN", "")  # Account security token
SF_DOMAIN         = os.getenv("SF_DOMAIN", "login")     # "login" (prod) or "test" (sandbox)

# ---------------------------------------------------------------------------
# Salesforce target Object
# ---------------------------------------------------------------------------
# TODO: Replace with your actual Custom Object API name (e.g. "Training_Result__c")
SF_OBJECT_API_NAME = "Training_Result__c"

# ---------------------------------------------------------------------------
# Field mapping: Excel field key → Salesforce field API name
#
# Left  side : keys from config.EXCEL_COLUMN_MAP  (e.g. "class_number")
# Right side : Salesforce field API names          (e.g. "Class_Number__c")
#
# TODO: Replace placeholder SF field names with your actual field API names.
#       Remove or comment out any fields that don't exist in your SF object.
# ---------------------------------------------------------------------------
SF_FIELD_MAP: dict[str, str] = {
    # --- Basic training info (Excel cols A–H) ---
    "class_number":                "Class_Number__c",
    "course_begin_date":           "Course_Begin_Date__c",
    "course_end_date":             "Course_End_Date__c",
    "training_center":             "Training_Center__c",
    "trainee_type":                "Trainee_Type__c",
    "trainee_account":             "Trainee_Account__c",
    "trainee_name":                "Trainee_Name__c",
    "training_course_description": "Training_Course_Description__c",

    # --- Evaluation scores Q1–Q15 (Excel cols I–W) ---
    "eval_q1":  "Eval_Q1__c",
    "eval_q2":  "Eval_Q2__c",
    "eval_q3":  "Eval_Q3__c",
    "eval_q4":  "Eval_Q4__c",
    "eval_q5":  "Eval_Q5__c",
    "eval_q6":  "Eval_Q6__c",
    "eval_q7":  "Eval_Q7__c",
    "eval_q8":  "Eval_Q8__c",
    "eval_q9":  "Eval_Q9__c",
    "eval_q10": "Eval_Q10__c",
    "eval_q11": "Eval_Q11__c",
    "eval_q12": "Eval_Q12__c",
    "eval_q13": "Eval_Q13__c",
    "eval_q14": "Eval_Q14__c",
    "eval_q15": "Eval_Q15__c",

    # --- Evaluation comments Q16–Q18 (Excel cols X–Z) ---
    "comment_q16": "Comment_Q16__c",
    "comment_q17": "Comment_Q17__c",
    "comment_q18": "Comment_Q18__c",

    # --- Survey single-select Q1–Q8 (Excel cols AA–AH) ---
    "survey_q1": "Survey_Q1__c",
    "survey_q2": "Survey_Q2__c",
    "survey_q3": "Survey_Q3__c",
    "survey_q4": "Survey_Q4__c",
    "survey_q5": "Survey_Q5__c",
    "survey_q6": "Survey_Q6__c",
    "survey_q7": "Survey_Q7__c",
    "survey_q8": "Survey_Q8__c",

    # --- Survey multi-select Q9_1–Q9_5 (Excel cols AI–AM) ---
    "survey_q9_1": "Survey_Q9_1__c",
    "survey_q9_2": "Survey_Q9_2__c",
    "survey_q9_3": "Survey_Q9_3__c",
    "survey_q9_4": "Survey_Q9_4__c",
    "survey_q9_5": "Survey_Q9_5__c",

    # --- Survey Likert Q10–Q39 (Excel cols AN–BQ) ---
    **{f"survey_q{i}": f"Survey_Q{i}__c" for i in range(10, 40)},
}

# ---------------------------------------------------------------------------
# Upload batch size  (Salesforce bulk API limit: 200 per call)
# ---------------------------------------------------------------------------
SF_BATCH_SIZE = 200
