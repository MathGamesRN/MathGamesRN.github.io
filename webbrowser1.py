import re
import sys
import webbrowser
def extract_titles(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    titles = re.findall(r'title:\s*"([^"]+)"', content)
    return titles
titles = extract_titles("games.js")
for a in titles:
    google = f"https://duckduckgo.com/?q={a}&ia=images&iax=images"
    webbrowser.open_new_tab(google)