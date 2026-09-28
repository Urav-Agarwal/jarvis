import json
import os


profile_file = os.path.expandvars(
    r"%LOCALAPPDATA%\Google\Chrome\User Data\Local State"
)

with open(profile_file, "r", encoding="utf-8") as file:
    data = json.load(file)

print("CHROME PROFILES:")

profiles = data.get("profile", {}).get("info_cache", {})

for profile_directory, profile_info in profiles.items():
    name = profile_info.get("name", "(unnamed)")
    print(f"{profile_directory} -> {name}")