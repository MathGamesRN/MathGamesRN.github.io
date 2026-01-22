import os

def generate_html_file(filename, html_content, folder_id):
    """
    Generate an HTML file in the games folder and create a folder in iframes.
    
    Args:
        filename (str): Name of the HTML file to create (e.g., 'game.html')
        html_content (str): The HTML code to write to the file
        folder_id (str): The ID for the folder to create in the iframes directory
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


if __name__ == "__main__":
    # Get user inputs
    game_name = input("Enter the name for the HTML file (without .html): ").strip()
    folder_id = input("Enter the folder ID for the iframes directory: ").strip()
    
    # Add .html extension if not provided
    if not game_name.endswith('.html'):
        game_name += '.html'
    
    # HTML Template
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Game</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background-color: #f0f0f0;
        }
        .container {
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Game</h1>
        <!-- Add your game content here -->
    </div>
</body>
</html>"""
    
    # Generate the file and folder
    generate_html_file(game_name, html_template, folder_id)
