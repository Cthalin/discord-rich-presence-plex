from app import cache, logger, config
from PIL import Image, ImageOps
from typing import Optional
import io
import requests

def isValidImageUrl(url: str) -> bool:
	"""Check if a URL is a valid image URL (not HTML error page)"""
	if not url or not isinstance(url, str):
		return False
	# Check if it looks like HTML (starts with <!doctype, <html, etc.)
	if url.strip().lower().startswith(("<!doctype", "<html", "<!html")):
		logger.warning(f"[IMAGE UPLOAD] Invalid cached URL detected (HTML content): {url[:100]}...")
		return False
	# Check if it's a valid HTTP/HTTPS URL
	if not url.startswith(("http://", "https://")):
		logger.warning(f"[IMAGE UPLOAD] Invalid cached URL (not HTTP/HTTPS): {url[:100]}...")
		return False
	# Check if it's suspiciously long (might be HTML)
	if len(url) > 500:
		logger.warning(f"[IMAGE UPLOAD] Cached URL suspiciously long ({len(url)} chars), might be HTML")
		return False
	return True

def upload(key: str, url: str) -> Optional[str]:
	logger.info(f"[IMAGE UPLOAD] Starting upload process for key: {key}, source URL: {url}")
	cachedValue = cache.get(key)
	if cachedValue:
		if isValidImageUrl(cachedValue):
			logger.info(f"[IMAGE UPLOAD] Found valid cached image URL: {cachedValue}")
			return cachedValue
		else:
			logger.warning(f"[IMAGE UPLOAD] Found invalid cached URL, clearing cache entry and re-uploading")
			# Clear the invalid cache entry
			cache.delete(key)
	logger.info(f"[IMAGE UPLOAD] Downloading image from: {url}")
	try:
		originalImageBytesIO = io.BytesIO(requests.get(url).content)
		logger.debug(f"[IMAGE UPLOAD] Downloaded image, size: {len(originalImageBytesIO.getvalue())} bytes")
	except Exception as e:
		logger.error(f"[IMAGE UPLOAD] Failed to download image from {url}: {e}")
		return None
	originalImage = Image.open(originalImageBytesIO).convert("RGBA")
	logger.debug(f"[IMAGE UPLOAD] Original image dimensions: {originalImage.width}x{originalImage.height}")
	newImage = Image.new("RGBA", originalImage.size)
	newImage.putdata(originalImage.getdata()) # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
	if newImage.width != newImage.height and config.config["display"]["posters"]["fit"]:
		longestSideLength = max(newImage.width, newImage.height)
		logger.debug(f"[IMAGE UPLOAD] Padding image to square: {longestSideLength}x{longestSideLength}")
		newImage = ImageOps.pad(newImage, (longestSideLength, longestSideLength), color = (0, 0, 0, 0))
	maxSize = config.config["display"]["posters"]["maxSize"]
	if maxSize:
		logger.debug(f"[IMAGE UPLOAD] Resizing image to max size: {maxSize}x{maxSize}")
		newImage.thumbnail((maxSize, maxSize))
		logger.debug(f"[IMAGE UPLOAD] Resized image dimensions: {newImage.width}x{newImage.height}")
	newImageBytesIO = io.BytesIO()
	newImage.save(newImageBytesIO, subsampling = 0, quality = 90, format = "PNG")
	pngBytes = newImageBytesIO.getvalue()
	logger.info(f"[IMAGE UPLOAD] Processed image, PNG size: {len(pngBytes)} bytes")
	logger.info("[IMAGE UPLOAD] Image upload disabled, skipping upload")
	return None

def getTmdbPosterUrl(tmdbId: str, mediaType: str, size: str = "w500") -> Optional[str]:
	"""Get TMDB poster URL for a given TMDB ID and media type.
	
	Args:
		tmdbId: The TMDB ID (e.g., "1399" for Game of Thrones)
		mediaType: "movie" or "episode" (for TV shows)
		size: Image size (w92, w154, w185, w342, w500, w780, original)
	
	Returns:
		TMDB poster URL or None if not found
	"""
	if not tmdbId or not config.config["display"]["posters"]["tmdbAPIKey"]:
		return None
	
	# Check cache first
	cacheKey = f"tmdb_{mediaType}_{tmdbId}_{size}"
	cachedUrl = cache.get(cacheKey)
	if cachedUrl:
		logger.debug(f"[TMDB] Using cached poster URL for TMDB ID {tmdbId}")
		return cachedUrl
	
	apiKey = config.config["display"]["posters"]["tmdbAPIKey"]
	
	# Determine endpoint based on media type
	if mediaType == "movie":
		endpoint = f"https://api.themoviedb.org/3/movie/{tmdbId}"
	elif mediaType in ["episode", "live_episode"]:
		# For TV shows, we need to get the show poster, not episode
		# We'll need the show's TMDB ID, which should be passed as tmdbId
		endpoint = f"https://api.themoviedb.org/3/tv/{tmdbId}"
	else:
		return None
	
	logger.debug(f"[TMDB] Fetching poster for {mediaType} with TMDB ID: {tmdbId}")
	
	try:
		response = requests.get(
			endpoint,
			params = { "api_key": apiKey },
			timeout = 5
		)
		response.raise_for_status()
		data = response.json()
		
		posterPath = data.get("poster_path")
		if not posterPath:
			logger.debug(f"[TMDB] No poster_path found for TMDB ID {tmdbId}")
			return None
		
		# TMDB CDN URL format: https://image.tmdb.org/t/p/{size}{poster_path}
		posterUrl = f"https://image.tmdb.org/t/p/{size}{posterPath}"
		logger.debug(f"[TMDB] Found poster URL: {posterUrl}")
		
		# Cache the URL (no expiry - TMDB URLs are permanent)
		cache.set(cacheKey, posterUrl, 0)
		return posterUrl
	except requests.exceptions.RequestException as e:
		logger.debug(f"[TMDB] Failed to fetch poster for TMDB ID {tmdbId}: {e}")
		return None
	except Exception as e:
		logger.debug(f"[TMDB] Error processing TMDB response for {tmdbId}: {e}")
		return None
