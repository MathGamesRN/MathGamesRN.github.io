import os
import re
import json

def generate_html_file(filename, html_content, folder_id, display_name):
    """
    Generate an HTML file in the games folder and create a folder in iframes.
    Automatically adds a link to the game in index.html.
    
    Args:
        filename (str): Name of the HTML file to create (e.g., 'game.html')
        html_content (str): The HTML code to write to the file
        folder_id (str): The ID for the folder to create in the iframes directory
        display_name (str): The display name for the game link
    """
    # Create games folder if it doesn't exist
    games_folder = os.path.join(os.path.dirname(__file__), 'games')
    if not os.path.exists(games_folder):
        os.makedirs(games_folder)
    
    # Create the HTML file path
    file_path = os.path.join(games_folder, filename)
    
    # Write the HTML content to the file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✓ Created HTML file: {file_path}")
    
    # Create iframes folder if it doesn't exist
    iframes_folder = os.path.join(os.path.dirname(__file__), 'iframes')
    if not os.path.exists(iframes_folder):
        os.makedirs(iframes_folder)
    
    # Create the folder in iframes with the specified ID
    id_folder = os.path.join(iframes_folder, folder_id)
    if not os.path.exists(id_folder):
        os.makedirs(id_folder)
    
    print(f"✓ Created folder: {id_folder}")
    
    # Add game to JSON file
    add_game_to_json(folder_id, display_name, filename)
    
    # Add link to index.html
    add_game_link_to_index(filename, display_name)


def add_game_to_json(folder_id, display_name, filename):
    """
    Add game information to a JSON file indexed by folder ID.
    
    Args:
        folder_id (str): The folder ID for the game (e.g., 'game_1')
        display_name (str): The display name for the game
        filename (str): The HTML filename
    """
    json_path = os.path.join(os.path.dirname(__file__), 'games.json')
    
    # Load existing games or create new dict
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            games = json.load(f)
    else:
        games = {}
    
    # Add or update the game entry
    games[folder_id] = {
        'name': display_name,
        'folder_id': folder_id
    }
    
    # Write back to JSON file
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(games, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Added game to games.json: {folder_id} -> {display_name}")


def get_next_folder_id():
    """
    Get the next folder ID by counting existing folders in iframes.
    
    Returns:
        str: The next folder ID (e.g., 'game_1', 'game_2', etc.)
    """
    iframes_folder = os.path.join(os.path.dirname(__file__), 'iframes')
    
    if not os.path.exists(iframes_folder):
        return 'game_1'
    
    # Count existing folders
    existing_folders = [f for f in os.listdir(iframes_folder) if os.path.isdir(os.path.join(iframes_folder, f))]
    next_id = len(existing_folders) + 1
    
    return f'game_{next_id}'


def add_game_link_to_index(filename, display_name):
    """
    Automatically add a game link to the index.html file.
    
    Args:
        filename (str): The HTML filename (e.g., 'game.html')
        display_name (str): The display name for the game link
    """
    index_path = os.path.join(os.path.dirname(__file__), 'index.html')
    
    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove .html extension from filename if present
    game_link = filename.replace('.html', '')
    
    # Create the game link HTML
    game_link_html = f'        <div class="{display_name}"><a href="/games/{filename}"><img src="/icons/{display_name}.png" width=200 height=200 class="icon" alt="{display_name}"><span class="popup_text">Play {display_name} today!</span></a></div>\n'
    
    # Check if the link already exists to avoid duplicates
    if f'href="/games/{filename}"' in content:
        print(f"⚠ Game link for '{filename}' already exists in index.html")
        return
    
    # Find the games div and add the link
    # Pattern to match the closing </div> of the games container
    pattern = r'(<div class="games">)(.*?)(</div>)'
    
    match = re.search(pattern, content, re.DOTALL)
    if match:
        # Insert the new game link before the closing </div>
        new_content = content[:match.end(2)] + '\n' + game_link_html + content[match.start(3):]
        
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✓ Added game link to index.html: {display_name}")
    else:
        print(f"✗ Could not find games container in index.html")


if __name__ == "__main__":
    # Get user input
    game_name = input("Enter the game name: ").strip()
    
    # Use the game name for both display name and filename
    display_name = game_name
    filename = game_name.replace(' ', '_').lower() + '.html'
    
    # Get the next folder ID automatically
    folder_id = get_next_folder_id()
    
    # HTML Template
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{display_name}</title>
    <link rel="stylesheet" href="../styles.css">
    <link rel="icon" href="../logo.png" type="image/x-icon">
</head>
<body>
    <header>
        <a href="/"><img src="../logo.png" alt="MathGamesRN Logo" width="150"/></a>
    </header>
    <div class="container">
    <button onclick="window.location.href='../iframes/{folder_id}/index.html'" class="FullScreen">Fullscreen/New tab</button>
        <h1>{display_name}</h1>
        <iframe src="../iframes/{folder_id}/index.html" width="800" height="600" frameborder="0" id="iframe" allowfullscreen></iframe>
    </div>
</body>
</html>"""
    
    # Generate the file and folder
    generate_html_file(filename, html_template, folder_id, display_name)
