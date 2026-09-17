from typing import Any, Literal
from pydantic import BaseModel, HttpUrl

Mode=Literal["LIVE","MOCK"]
Stage=Literal["IDLE","VALIDATING_URL","DISCOVERING","FETCHING","PARSING","STRUCTURING","VALIDATING_DATA","READY","COMPLETED","PARTIAL_SUCCESS","DEMO_MODE","ERROR"]
TABLES=["store","categories","products","product_categories","images","product_options","option_values","variants","variant_option_values","tags","product_tags","seo","validation_issues"]
class ExtractRequest(BaseModel):
    store_url:str
    extraction_mode:Literal["QUICK","FULL"]="QUICK"
class Issue(BaseModel):
    Severity: Literal["INFO","WARNING","ERROR"]; Entity_Type:str; Entity_ID:str|None=None; Field:str|None=None; Issue:str; Original_Value:Any=None
class Session(BaseModel):
    id:str; stage:Stage; mode:Mode|None=None; extraction_mode:Literal["QUICK","FULL"]="QUICK"; message:str; progress_current:int=0; progress_total:int|None=None; progress_percentage:float=0
    tables:dict[str,list[dict[str,Any]]]={}; raw_data:dict[str,Any]={}; stats:dict[str,Any]={}; issues:list[Issue]=[]
