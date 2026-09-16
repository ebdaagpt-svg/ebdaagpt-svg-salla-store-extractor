from typing import Any, Literal
from pydantic import BaseModel, HttpUrl

Mode=Literal["LIVE","MOCK"]
Stage=Literal["IDLE","VALIDATING_URL","DISCOVERING","FETCHING","PARSING","STRUCTURING","VALIDATING_DATA","READY","PARTIAL_SUCCESS","DEMO_MODE","ERROR"]
TABLES=["store","categories","products","product_categories","images","product_options","option_values","variants","variant_option_values","tags","product_tags","seo","validation_issues"]
class ExtractRequest(BaseModel): store_url:str
class Issue(BaseModel):
    Severity: Literal["INFO","WARNING","ERROR"]; Entity_Type:str; Entity_ID:str|None=None; Field:str|None=None; Issue:str; Original_Value:Any=None
class Session(BaseModel):
    id:str; stage:Stage; mode:Mode|None=None; message:str; progress_current:int=0; progress_total:int|None=None
    tables:dict[str,list[dict[str,Any]]]={}; raw_data:dict[str,Any]={}; stats:dict[str,Any]={}; issues:list[Issue]=[]
