#!/usr/bin/env python3
"""
Diagnostic script to check what PANEL_LOGIN and PANEL_PASSWORD values
the backend actually sees from environment.
"""
import os
import sys

login = os.getenv('PANEL_LOGIN', '')
password = os.getenv('PANEL_PASSWORD', '')

print("=== Panel Auth Environment Check ===")
print(f"PANEL_LOGIN: {repr(login)}")
print(f"  - length: {len(login)}")
print(f"  - stripped length: {len(login.strip())}")
print(f"  - first 5 chars: {repr(login[:5])}")
print(f"  - last 5 chars: {repr(login[-5:])}")
print()
print(f"PANEL_PASSWORD: {'<SET>' if password else '<EMPTY>'}")
print(f"  - length: {len(password)}")
print(f"  - stripped length: {len(password.strip())}")
print(f"  - first 3 chars: {repr(password[:3])}")
print(f"  - last 3 chars: {repr(password[-3:])}")
print()

# Check for common issues
issues = []
if login.startswith(' ') or login.endswith(' '):
    issues.append("⚠️  PANEL_LOGIN has leading or trailing whitespace")
if password.startswith(' ') or password.endswith(' '):
    issues.append("⚠️  PANEL_PASSWORD has leading or trailing whitespace")
if login.startswith('"') or login.startswith("'"):
    issues.append("⚠️  PANEL_LOGIN starts with a quote character")
if password.startswith('"') or password.startswith("'"):
    issues.append("⚠️  PANEL_PASSWORD starts with a quote character")
if '\n' in login or '\r' in login:
    issues.append("⚠️  PANEL_LOGIN contains newline characters")
if '\n' in password or '\r' in password:
    issues.append("⚠️  PANEL_PASSWORD contains newline characters")

if issues:
    print("Issues found:")
    for issue in issues:
        print(f"  {issue}")
    sys.exit(1)
else:
    print("✓ No obvious formatting issues detected")
    sys.exit(0)
