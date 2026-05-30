def generate_nutrition_label(data):
    template = "식품명: {{name}} | 영양소명: {{nutrient}} | 함량: {{value}}g"
    return template.format(**data)