Analysis Options
================

Get available SN types and age bins for DASH templates.

Endpoint
--------

.. code-block:: text

   GET /api/v1/analysis-options

Description
-----------

Returns the list of available supernova types and their corresponding age bins for use in spectrum processing, classification, or template matching.

Request
-------

No parameters required.

Response
--------

Success Response
~~~~~~~~~~~~~~~~

**Status Code:** ``200 OK``

.. code-block:: json

   {
     "sn_types": ["Ia-norm", "Ib-norm", "..."],
     "age_bins_by_type": {
       "Ia-norm": ["-10 to -6", "-6 to -2", "..."],
       "..."
     }
   }

Error Response
~~~~~~~~~~~~~~

**Status Code:** ``500 Internal Server Error``

.. code-block:: json

   {
     "detail": "Fetching analysis options failed"
   }

Example
-------

cURL
~~~~

.. code-block:: bash

   curl -X GET "http://localhost:8000/api/v1/analysis-options"

Python
~~~~~~

.. code-block:: python

   import requests
   response = requests.get('http://localhost:8000/api/v1/analysis-options')
   print(response.json())

Notes
-----

- Use these SN types and age bins as valid values for other endpoints (e.g., ``/api/v1/template-spectrum``).

Common Errors
-------------

- 500: Configuration error (template file missing)

  .. code-block:: json

     { "detail": "Failed to fetch analysis options: ..." }
