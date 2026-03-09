Architecture Overview
=====================

AstroDASH 2.0 follows a clean, layered architecture for maintainability and testability. All code is open sourced and available at https://github.com/jesusCaraball0/astrodash-web

High-level layers
-----------------

1. API Layer (FastAPI)

   - Routers under ``app/api/v1/`` expose versioned endpoints
   - Validation via Pydantic schemas; global exception handlers and middleware

2. Domain Services

   - Business logic for spectrum processing, classification, redshift, models, batches, templates, line lists
   - Reside in ``app/domain/services/``

3. Repositories and Storage

   - Abstractions for spectrum and model persistence and retrieval
   - File-based storage, SQLAlchemy repositories, and OSC API client
   - Reside in ``app/domain/repositories/`` and ``app/infrastructure/*``

4. ML Infrastructure

   - Classifiers (Dash, Transformer, User) and preprocessing utilities
   - Template handling, RLAP computation, and data processing
   - Reside in ``app/infrastructure/ml/*``

5. Core & Config

   - Exception handling, middleware, logging, settings
   - Reside in ``app/core/*`` and ``app/config/*``

Request flow (example: POST /api/v1/process)
---------------------------------------------

1. API router parses form data (``file``, ``params``) and injects dependencies
2. ``SpectrumService`` obtains spectrum data (file or OSC)
3. ``SpectrumProcessingService`` applies filtering, smoothing, normalization, metadata
4. ``ClassificationService`` selects appropriate classifier (Dash/Transformer/User) via ``ModelFactory``
5. ML classifier runs inference
6. Response is serialized with sanitized numeric types

Dependency injection
--------------------

The ``app/core/dependencies.py`` module wires services, repositories, and config through FastAPI ``Depends`` for testability and configuration.

Error handling
--------------

All exceptions are mapped to structured JSON errors in ``app/core/exceptions.py``, with precise HTTP status codes and sanitized messages.
