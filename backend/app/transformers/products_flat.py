from collections import defaultdict


def build_products_flat(tables: dict) -> list[dict]:
    """Create an import-friendly one-row-per-product view from normalized tables."""
    categories = {str(row.get("Category_ID")): row for row in tables.get("categories", [])}
    product_categories = defaultdict(list)
    images = defaultdict(list)
    variants = defaultdict(list)
    options = defaultdict(list)
    tags = {str(row.get("Tag_ID")): row for row in tables.get("tags", [])}
    product_tags = defaultdict(list)

    for row in tables.get("product_categories", []):
        product_categories[str(row.get("Product_ID"))].append(row)
    for row in tables.get("images", []):
        images[str(row.get("Product_ID"))].append(row)
    for row in tables.get("variants", []):
        variants[str(row.get("Product_ID"))].append(row)
    for row in tables.get("product_options", []):
        options[str(row.get("Product_ID"))].append(row)
    for row in tables.get("product_tags", []):
        product_tags[str(row.get("Product_ID"))].append(row)

    rows = []
    for product in tables.get("products", []):
        pid = str(product.get("Product_ID"))
        category_rows = [categories.get(str(link.get("Category_ID")), {}) for link in product_categories[pid]]
        image_rows = sorted(images[pid], key=lambda row: row.get("Display_Order") or 999999)
        variant_rows = variants[pid]
        tag_rows = [tags.get(str(link.get("Tag_ID")), {}) for link in product_tags[pid]]
        main_image = next((row.get("Image_URL") for row in image_rows if row.get("Is_Main")), None)
        rows.append({
            **product,
            "Category_IDs": " | ".join(str(row.get("Category_ID")) for row in category_rows if row.get("Category_ID") is not None) or None,
            "Category_Names": " | ".join(str(row.get("Name")) for row in category_rows if row.get("Name")) or None,
            "Category_URLs": " | ".join(str(row.get("URL")) for row in category_rows if row.get("URL")) or None,
            "Main_Image_URL": main_image or (image_rows[0].get("Image_URL") if image_rows else None),
            "Image_URLs": " | ".join(str(row.get("Image_URL")) for row in image_rows if row.get("Image_URL")) or None,
            "Image_Count": len(image_rows),
            "Variant_Count": len(variant_rows),
            "Variant_SKUs": " | ".join(str(row.get("SKU")) for row in variant_rows if row.get("SKU")) or None,
            "Option_Names": " | ".join(str(row.get("Option_Name")) for row in options[pid] if row.get("Option_Name")) or None,
            "Tag_Names": " | ".join(str(row.get("Name")) for row in tag_rows if row.get("Name")) or None,
        })
    return rows
