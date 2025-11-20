import requests
from typing import List, Dict, Optional


class SubSourceClient:
    BASE_URL = "https://api.subsource.net/api/v1"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            'X-API-Key': api_key
        }
    
    def search_movie(self, imdb_id: str, season: int = None) -> Optional[Dict]:
        """Search for movie/series by IMDB ID"""
        url = f"{self.BASE_URL}/movies/search"
        params = {
            'searchType': 'imdb',
            'imdb': imdb_id
        }
        
        if season is not None:
            params['season'] = season
        
        response = requests.get(url, headers=self.headers, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get('success') and data.get('data'):
            return data['data'][0]  # Return first match
        return None
    
    def get_subtitles(self, movie_id: int, language: str = None, page: int = 1, limit: int = 20) -> Dict:
        """Get subtitles for a movie/series"""
        url = f"{self.BASE_URL}/subtitles"
        params = {
            'movieId': movie_id,
            'page': page,
            'limit': limit
        }
        
        if language:
            params['language'] = language
        
        response = requests.get(url, headers=self.headers, params=params, timeout=10)
        response.raise_for_status()
        
        return response.json()
    
    def download_subtitle(self, subtitle_id: int) -> bytes:
        """Download subtitle ZIP file"""
        url = f"{self.BASE_URL}/subtitles/{subtitle_id}/download"
        
        response = requests.get(url, headers=self.headers, timeout=30)
        response.raise_for_status()
        
        # SubSource returns JSON with body field containing ZIP stream
        body = response.content
        
        return body
