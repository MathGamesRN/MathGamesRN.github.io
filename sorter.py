import re
import os

def sort_games_in_index():
    """
    Sorts all game links in index.html alphabetically by display name.
    """
    index_path = os.path.join(os.path.dirname(__file__), 'index.html')
    
    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all game divs within the games container
    # Pattern to match: <div class="gamename"><a href="...">...</a></div>
    game_pattern = r'        <div class="[^"]+"><a href="/games/[^"]+"><img src="/icons/[^"]+\.png"[^>]*><p class="popup_text">[^<]+</p></a></div>'
    
    games = re.findall(game_pattern, content)
    
    if not games:
        print("✗ No games found in index.html")
        return
    
    # Extract display names and sort
    def get_display_name(game_html):
        match = re.search(r'alt="([^"]+)"', game_html)
        return match.group(1) if match else ""
    
    sorted_games = sorted(games, key=get_display_name)
    
    # Create the new games container content
    games_content = '\n'.join(['        <!-- Game links will be added here -->\n    '] + sorted_games)
    
    # Replace the old games container with the sorted one
    pattern = r'(<div class="games">)(.*?)(</div>\s*</main>)'
    
    match = re.search(pattern, content, re.DOTALL)
    if match:
        new_content = match.group(1) + '\n' + games_content + '\n' + match.group(3)
        
        # Replace the entire matched section
        new_full_content = content[:match.start()] + new_content + content[match.end():]
        
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(new_full_content)
        
        print(f"✓ Sorted {len(sorted_games)} games alphabetically")
        for game in sorted_games:
            display_name = get_display_name(game)
            print(f"  - {display_name}")
    else:
        print("✗ Could not find games container in index.html")

if __name__ == "__main__":
    sort_games_in_index()
