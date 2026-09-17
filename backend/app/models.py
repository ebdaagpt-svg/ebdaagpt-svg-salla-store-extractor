from typing import Any, Literal
from pydantic import BaseModel, Field

Mode=Literal["LIVE","MOCK"]
Stage=Literal["IDLE","VALIDATING_URL","DISCOVERING","FETCHING","PARSING","STRUCTURING","VALIDATING_DATA","READY","COMPLETED","COMPLETED_WITH_ERRORS","PARTIAL_SUCCESS","DEMO_MODE","ERROR"]
TABLES=["store","website_data","categories","products","products_flat","product_categories","images","product_options","option_values","variants","variant_option_values","tags","product_tags","seo","validation_issues"]
class ExtractRequest(BaseModel):
    store_url:str
    data_type:Literal["PRODUCTS","CATEGORIES","WEBSITE"]="PRODUCTS"
    extraction_mode:Literal["QUICK","FULL"]="QUICK"
    max_products:int|None=Field(default=None,ge=1,le=1000)
class Issue(BaseModel):
    Severity: Literal["INFO","WARNING","ERROR"]; Entity_Type:str; Entity_ID:str|None=None; Field:str|None=None; Issue:str; Original_Value:Any=None
class Session(BaseModel):
    id:str; stage:Stage; mode:Mode|None=None; data_type:Literal["PRODUCTS","CATEGORIES","WEBSITE"]="PRODUCTS"; extraction_mode:Literal["QUICK","FULL"]="QUICK"; max_products:int|None=None; message:str; progress_current:int=0; progress_total:int|None=None; progress_percentage:float=0
    tables:dict[str,list[dict[str,Any]]]={}; raw_data:dict[str,Any]={}; stats:dict[str,Any]={}; issues:list[Issue]=[]
