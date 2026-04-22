import os
from dotenv import load_dotenv

load_dotenv()

SF_USERNAME       = os.getenv("SF_USERNAME", "")
SF_PASSWORD       = os.getenv("SF_PASSWORD", "")
SF_SECURITY_TOKEN = os.getenv("SF_SECURITY_TOKEN", "")
SF_DOMAIN         = os.getenv("SF_DOMAIN", "login")

SF_OBJECT_API_NAME = "Training_Result__c"

SF_FIELD_MAP: dict[str, str] = {
    "class_number":                "Class_Number__c",
    "course_begin_date":           "Course_Begin_Date__c",
    "course_end_date":             "Course_End_Date__c",
    "training_center":             "Training_Center__c",
    "trainee_type":                "Trainee_Type__c",
    "trainee_account":             "Trainee_Account__c",
    "trainee_name":                "Trainee_Name__c",
    "training_course_description": "Training_Course_Description__c",
    **{f"eval_q{i}": f"Eval_Q{i}__c" for i in range(1, 16)},
    "comment_q16": "Comment_Q16__c",
    "comment_q17": "Comment_Q17__c",
    "comment_q18": "Comment_Q18__c",
    **{f"survey_q{i}": f"Survey_Q{i}__c" for i in range(1, 9)},
    **{f"survey_q9_{i}": f"Survey_Q9_{i}__c" for i in range(1, 6)},
    **{f"survey_q{i}": f"Survey_Q{i}__c" for i in range(10, 40)},
}

SF_BATCH_SIZE = 200
