# Legacy API Implementation

This directory contains legacy code that has been replaced by the modular API structure.

## Files

- **`legacy_api_app.py`** - Original single-file FastAPI implementation

## ⚠️ DO NOT USE IN PRODUCTION

This code is kept for reference only. It has been replaced by the modular API structure in `api/`.

**Correct production entrypoint:**
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

## Migration Notes

- All endpoints are now in `api/routers/`
- Schemas are in `api/schemas/`
- Services are in `api/services/`
- Main app entrypoint is `api/main.py`

This legacy code will be removed in a future release.
