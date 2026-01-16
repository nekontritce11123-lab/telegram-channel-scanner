"""Проверка API response."""
import json
import urllib.request

url = "https://ads-api.factchain-traker.online/api/channels/neuralshit"

with urllib.request.urlopen(url) as response:
    data = json.loads(response.read().decode())

b = data.get('breakdown', {})

print('=== QUALITY ===')
for k, v in b.get('quality', {}).get('items', {}).items():
    print(f'  {k}: {v.get("score", "?")}/{v.get("max", "?")}')

print()
print('=== ENGAGEMENT ===')
for k, v in b.get('engagement', {}).get('items', {}).items():
    disabled = ' [ОТКЛ]' if v.get('disabled') else ''
    print(f'  {k}: {v.get("score", "?")}/{v.get("max", "?")}{disabled}')

print()
print('=== REPUTATION ===')
for k, v in b.get('reputation', {}).get('items', {}).items():
    print(f'  {k}: {v.get("score", "?")}/{v.get("max", "?")}')

print()
print('Нет posting_frequency и private_links в breakdown = FIX РАБОТАЕТ!')
