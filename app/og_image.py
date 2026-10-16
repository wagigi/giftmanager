"""Preview image lookup (og:image, twitter:image, image_src) for gift links."""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from requests.packages.urllib3.exceptions import InsecureRequestWarning


requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


def fetch_og_image(url):
    try:
        response = requests.get(url, verify=False)
        response.raise_for_status()  # Raise an error for bad status codes
        soup = BeautifulSoup(response.text, 'html.parser')

        # Try to get the og:image tag
        og_image = soup.find('meta', property='og:image')
        if og_image:
            image_url = og_image.get('content')
            # Convert relative URL to absolute URL if necessary
            if not image_url.startswith('http'):
                image_url = urljoin(url, image_url)
            return image_url

        # Fallback to twitter:image if og:image is not found
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image:
            image_url = twitter_image.get('content')
            if not image_url.startswith('http'):
                image_url = urljoin(url, image_url)
            return image_url

        # Fallback to image_src if og:image and twitter:image are not found
        image_src = soup.find('link', rel='image_src')
        if image_src:
            image_url = image_src.get('href')
            if not image_url.startswith('http'):
                image_url = urljoin(url, image_url)
            return image_url

        return None  # No image found
    except Exception as e:
        print(f"Error fetching OG image: {e}")
        return None
