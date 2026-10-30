"""Resident speech service protocol and client."""
from .client import AudioChunk, SpeechError, SpeechServiceClient, SpeechServiceManager

__all__ = ["AudioChunk", "SpeechError", "SpeechServiceClient", "SpeechServiceManager"]
