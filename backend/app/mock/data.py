from datetime import datetime, timezone
from backend.app.utils import stable_id

def mock_catalog():
    cats=[("electronics",None,"الإلكترونيات"),("phones","electronics","الهواتف"),("home",None,"المنزل"),("coffee","home","القهوة"),("accessories",None,"الإكسسوارات")]
    categories=[]
    for i,(slug,parent,name) in enumerate(cats,1): categories.append({"Category_ID":slug,"Parent_Category_ID":parent,"Name":name,"Slug":slug,"URL":f"https://demo.invalid/c/{slug}","Description":None,"Display_Order":i,"Is_Active":True})
    products=[]; pc=[]; images=[]; options=[]; values=[]; variants=[]; variant_values=[]; tags=[{"Tag_ID":"new","Name":"جديد","Slug":"new"},{"Tag_ID":"featured","Name":"مميز","Slug":"featured"}]; product_tags=[]; seo=[]
    for i in range(1,21):
        pid=f"P{i:03}"; cat=cats[i%len(cats)][0]; sale=round(89+i*11.25,2) if i%3==0 else None
        products.append({"Product_ID":pid,"Title":f"منتج تجريبي {i}","Slug":f"demo-product-{i}","SKU":None if i==7 else f"SKU-{1000+i}","Barcode":f"628{i:010}","Product_Type":"physical","Price":round(120+i*13.5,2),"Sale_Price":sale,"Currency":"SAR","Cost_Price":None,"Quantity":None if i%6==0 else i*2,"Is_Available":i%5!=0,"Is_Active":True,"Brand":"علامة تجريبية","Weight":0.5 if i%2 else 1.0,"Weight_Unit":"kg","Short_Description":f"وصف مختصر للمنتج {i}","Description_HTML":f"<p>وصف عربي <strong>تجريبي</strong> للمنتج {i}</p>","Description_Text":f"وصف عربي تجريبي للمنتج {i}","Product_URL":f"https://demo.invalid/p/{i}","Created_At":None,"Updated_At":None})
        pc.append({"Product_ID":pid,"Category_ID":cat,"Is_Primary":True})
        if i!=11:
            for j in range(1,3): images.append({"Image_ID":f"IMG{i:03}-{j}","Product_ID":pid,"Image_URL":f"https://picsum.photos/seed/salla-{i}-{j}/800/800","Alt_Text":f"منتج {i}","Display_Order":j,"Is_Main":j==1})
        if i<=6:
            oid=f"OPT{i:03}"; options.append({"Option_ID":oid,"Product_ID":pid,"Option_Name":"اللون","Display_Order":1})
            for j,color in enumerate(["أسود","أبيض"],1):
                vid=f"VAL{i:03}-{j}"; varid=f"VAR{i:03}-{j}"; values.append({"Option_Value_ID":vid,"Option_ID":oid,"Value":color,"Display_Order":j}); variants.append({"Variant_ID":varid,"Product_ID":pid,"SKU":f"SKU-{1000+i}-{j}","Barcode":None,"Price":round(120+i*13.5,2),"Sale_Price":sale,"Quantity":j*3,"Is_Available":True,"Weight":0.5,"Weight_Unit":"kg"}); variant_values.append({"Variant_ID":varid,"Option_ID":oid,"Option_Value_ID":vid})
        product_tags.append({"Product_ID":pid,"Tag_ID":"featured" if i%2 else "new"}); seo.append({"Entity_Type":"PRODUCT","Entity_ID":pid,"Meta_Title":f"منتج تجريبي {i}","Meta_Description":f"بيانات تجريبية للمنتج {i}","Canonical_URL":f"https://demo.invalid/p/{i}"})
    store=[{"Store_ID":"mock-store","Store_Name":"متجر سلة التجريبي","Store_URL":"https://demo.invalid/","Currency":"SAR","Language":"ar","Extraction_Date":datetime.now(timezone.utc).isoformat(),"Data_Mode":"MOCK","Extractor_Version":"1.8.1"}]
    return {"store":store,"website_data":[],"categories":categories,"products":products,"product_categories":pc,"images":images,"product_options":options,"option_values":values,"variants":variants,"variant_option_values":variant_values,"tags":tags,"product_tags":product_tags,"seo":seo}


def mock_website_data():
    extracted_at = datetime.now(timezone.utc).isoformat()
    store = [{"Store_ID":"mock-website","Store_Name":"متجر سلة التجريبي","Store_URL":"https://demo.invalid/","Currency":"SAR","Language":"ar","Extraction_Date":extracted_at,"Data_Mode":"MOCK","Extractor_Version":"1.8.1"}]
    values = {
        "Store_Name":"متجر سلة التجريبي",
        "Description":"بيانات موقع تجريبية لاختبار المعاينة فقط",
        "Logo_URL":"https://demo.invalid/logo.png",
        "Phone":"+966500000000",
        "Email":"hello@demo.invalid",
        "Address_Street":"طريق الملك فهد",
        "Location_City":"الرياض",
        "Location_Region":"منطقة الرياض",
        "Country":"SA",
        "Social_Instagram":"https://instagram.com/demo",
        "Social_X_Twitter":"https://x.com/demo",
    }
    rows = [{"Field":field,"Value":value,"Source_URL":"https://demo.invalid/","Source_Strategy":"MOCK"} for field,value in values.items()]
    return {"store":store,"website_data":rows}
