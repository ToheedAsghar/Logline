import urllib.request
import zipfile
import os

os.makedirs("tracker-app/Fonts", exist_ok=True)

def download_and_extract(url, name, font_files):
    print(f"Downloading {name}...")
    zip_path = f"scratch/{name}.zip"
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for file in zip_ref.namelist():
            for font_file in font_files:
                if file.endswith(font_file) or file.endswith("OFL.txt"):
                    zip_ref.extract(file, "tracker-app/Fonts")
                    # Move to root of Fonts if it's in a subdirectory
                    extracted_path = os.path.join("tracker-app/Fonts", file)
                    target_path = os.path.join("tracker-app/Fonts", os.path.basename(file))
                    if extracted_path != target_path:
                        os.rename(extracted_path, target_path)
                        try:
                            os.rmdir(os.path.dirname(extracted_path))
                        except:
                            pass

download_and_extract(
    "https://fonts.google.com/download?family=Space%20Grotesk",
    "Space_Grotesk",
    ["SpaceGrotesk-Regular.ttf", "SpaceGrotesk-Medium.ttf", "SpaceGrotesk-SemiBold.ttf", "SpaceGrotesk-Bold.ttf"]
)

download_and_extract(
    "https://fonts.google.com/download?family=JetBrains%20Mono",
    "JetBrains_Mono",
    ["JetBrainsMono-Regular.ttf", "JetBrainsMono-Medium.ttf", "JetBrainsMono-Bold.ttf"]
)

print("Done downloading fonts.")
