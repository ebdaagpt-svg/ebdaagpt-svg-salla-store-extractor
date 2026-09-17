from collections import Counter
from backend.app.models import Issue

def validate_catalog(t):
    issues=[]; pids={x["Product_ID"] for x in t["products"]}; cids={x["Category_ID"] for x in t["categories"]}; image_pids={x["Product_ID"] for x in t["images"]}; pc_pids={x["Product_ID"] for x in t["product_categories"]}
    def add(sev,typ,eid,field,msg,val=None): issues.append(Issue(Severity=sev,Entity_Type=typ,Entity_ID=eid,Field=field,Issue=msg,Original_Value=val))
    for p in t["products"]:
        pid=p["Product_ID"]
        if not p.get("Title"):add("ERROR","PRODUCT",pid,"Title","Missing product title")
        if not p.get("SKU"):add("WARNING","PRODUCT",pid,"SKU","Product has no public SKU")
        if pid not in image_pids:add("WARNING","PRODUCT",pid,"Images","Product has no images")
        if t["categories"] and pid not in pc_pids:add("WARNING","PRODUCT",pid,"Categories","Product has no category relationship")
        for field in ("Price","Sale_Price"):
            val=p.get(field)
            if val is not None and val<0:add("ERROR","PRODUCT",pid,field,"Price cannot be negative",val)
        if p.get("Price") is not None and p.get("Sale_Price") is not None and p["Sale_Price"]>p["Price"]:add("WARNING","PRODUCT",pid,"Sale_Price","Sale price exceeds regular price",p["Sale_Price"])
    for field in ("SKU","Product_URL"):
        counts=Counter(p[field] for p in t["products"] if p.get(field))
        for val,count in counts.items():
            if count>1:add("WARNING","PRODUCT",None,field,f"Duplicate {field} across {count} products",val)
    for row in t["product_categories"]:
        if row["Product_ID"] not in pids or row["Category_ID"] not in cids:add("ERROR","PRODUCT_CATEGORY",row.get("Product_ID"),None,"Broken product-category relationship",row)
    for row in t["categories"]:
        if row.get("Parent_Category_ID") and row["Parent_Category_ID"] not in cids:add("ERROR","CATEGORY",row.get("Category_ID"),"Parent_Category_ID","Category parent does not exist",row["Parent_Category_ID"])
    for row in t["images"]:
        if row["Product_ID"] not in pids:add("ERROR","IMAGE",row.get("Image_ID"),"Product_ID","Image parent product does not exist",row["Product_ID"])
    for row in t["variants"]:
        if row["Product_ID"] not in pids:add("ERROR","VARIANT",row.get("Variant_ID"),"Product_ID","Variant parent product does not exist",row["Product_ID"])
    return issues
