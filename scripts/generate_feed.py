import requests

print("Завантаження XML...")

url = "https://catpaws.com.ua/content/export/f58d0310c9401a7213540d5b6d75420a.xml"

r = requests.get(url, timeout=60)

print("Статус:", r.status_code)

print("Розмір:", len(r.text))
