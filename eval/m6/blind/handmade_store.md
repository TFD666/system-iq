# Blind review: handmade_store

## Design X

## 1. Architecture overview
We implement a modular monolith to match the small budget and two-developer team. This style keeps deployment and operational complexity low while allowing clear internal boundaries for future separation if scale demands it. The architecture centers on a single deployable backend service, a persistent relational database, object storage for media, and a third-party payment provider. This choice avoids the overhead of microservices messaging infrastructure that is unjustified at this scale.

## 2. Components and responsibilities
- **Authentication Module**: Handles buyer and seller account creation, login, and role-based permission enforcement.
- **Catalog Module**: Manages product listing data, photo metadata, and search indexing capabilities.
- **Order Module**: Processes payment initiation via card providers and tracks order status through completion.
- **Dashboard Module**: Provides seller interfaces for listing management and payout viewing.
- **Payment Gateway Client**: Integrates with the external payment provider for transaction processing and refunds.
- **Media Storage Handler**: Interfaces with object storage to upload, retrieve, and serve product photos.

## 3. Data flow
A user request enters through the web interface, routed to the relevant backend module. Authentication validates the session token before proceeding. For purchases, the Order Module calls the Payment Gateway Client to process the card transaction. Upon success, it writes the new order record to the relational database and updates inventory counts. For browsing, the Catalog Module queries the database for product details and constructs signed URL references to object storage for retrieving photos, returning the combined data to the client.

## 4. API architecture
I will adopt a REST API because standard HTTP verbs perfectly model e-commerce resources like listings, customer profiles, and checkout sessions. This approach simplifies integration with the third-party payment provider.

Key operations include:
*   **Catalog**: `GET /products` supports filtering and full-text search parameters to facilitate faster product discovery.
*   **Orders**: `POST /orders` initiates payment via the provider, while `GET /orders/{id}` provides real-time status tracking.
*   **Dashboard**: `POST /products` and `PATCH /products/{id}` allow sellers to manage inventory and upload photo references.

I will use URI versioning (`/api/v1/` for initial rollout) to ensure backward compatibility as features are added. Errors will follow standard RFC 7807 JSON-RFC 7807 Problem Details for consistent client handling.

## 5. Database architecture and data model
PostgreSQL is the optimal choice because it natively manages relational integrity for rigorous financial flows and includes the `pg_trgm` extension for efficient text searching. This single relational engine handles all core data needs without external dependencies.

Core entities include:
*   **Users**: Stores first and last names, email addresses, and role flags for strict buyer/seller separation.
*   **Products**: Contains descriptive text, price values, and arrays of photo URLs pointing to the media system.
*   **Orders**: Tracks transactional status, total sums, and payment provider reference IDs for secure reconciliation.

The schema utilizes standard foreign keys: each order belongs to exactly one user and contains many line items. Since the scale is approximately 200 sellers, baseline B-tree indexing on foreign keys and search columns is sufficient. Partitioning is unnecessary at this data volume.

## 6. Authentication
Role-based authentication protects the client application and backend APIs for both buyers and sellers. Buyers require standard account authentication to access order tracking and purchase history, while sellers use credentials to secure access to the listing and payout management dashboards. JSON Web Tokens are issued upon successful login to validate subsequent requests. The token lifetime is set to one hour to balance user convenience with security session management for this web-based interface.

## 7. Caching
Database caching is required to handle the expected 500 requests per second with limited hardware resources. A Redis instance serves as the primary caching layer. It stores commodity product data, session tokens, and active payment verification states. This approach reduces unnecessary database queries for frequent browsing and search operations, improving response times while keeping infrastructure costs aligned with the small budget constraint.

## 8. External services
This project depends on two primary external integrations. A payment provider service processes all card transactions and manages the transfer of funds to sellers. A cloud object storage service hosts high-resolution product photos, serving as the persistent media repository for the catalog. Both services operate through standard REST APIs to ensure seamless data exchange with the core application architecture.

## 9. Security considerations
- Validate all user inputs, particularly product search parameters and form data, to prevent SQL injection and cross-site scripting attacks.
- Store API keys and database credentials in a secure environment variable manager or secret store, never in source code.
- Implement strict role-based access control middleware to ensure buyers cannot access seller dashboards while sellers cannot modify other users' data.

## 10. Scaling
The system is designed to scale horizontally by adding application server instances behind a load balancer. Given the peak of 500 requests per second, a single node may be insufficient, so stateless services allow for simple capacity increases. Object storage handles photo volume independently from compute resources. Database scaling remains vertical initially, with read replicas added if query latency rises. This approach keeps infrastructure costs low while accommodating growth for the 200 sellers.

## 11. Failure handling
When the external payment provider fails, the system returns a clear error to the user and advises retrying the transaction later. Application services include timeout limits and retry logic for non-idempotent operations to prevent duplicate charges. If object storage becomes unavailable, product pages display cached images while new uploads are queued. The authentication service uses healthy check endpoints to fail fast, preventing sessions from entering an inconsistent state during outages.

## 12. Trade-offs and rationale
- **Managed services over self-hosting:** Reduces DevOps overhead for the two-developer team, though at a higher per-unit cost.
- **Synchronous payment processing:** Ensures order consistency and simplicity, sacrificing background processing complexity.
- **Relational database:** Provides strong transactional integrity for orders and payments, limitting scalability compared to NoSQL options.
- **Standard REST APIs:** Prioritize developer velocity and ease of integration over the performance of WebSockets.

## Design Y

## 1. Architecture overview
The project proposes a monolithic architecture, a choice intended to be confirmed given the team size of two developers and a limited budget. This style minimizes infrastructure complexity, which is critical for a small operational footprint. The main building blocks include a single application server handling all business logic, a persistent relational data store, and an external interface for secure transactions. While a modular monolith structure was considered as an alternative to improve code organization, the current proposal favors a simpler, unified deployment model to reduce maintenance overhead and operational costs.

## 2. Components and responsibilities
- **Catalog Service**: Manages product listings, including photos, and provides search and filtering capabilities for buyers.
- **Payment Gateway**: Integrates with an external provider to process secure card payments for all transactions.
- **Order Management**: Handles the creation of new orders and tracks their status from placement to delivery.
- **Seller Control**: Enables sellers to manage their inventory listings and view financial details related to their sales.
- **Payout Engine**: Calculates and initiates financial transfers to sellers following completed orders.
- **Admin Dashboard**: Allows site administrators to monitor overall health and manage the approximately 200 registered seller accounts.

## 3. Data flow
A buyer initiates a request through the client application, which is routed to the backend via REST endpoints. The system retrieves product details and images from the PostgreSQL database. Upon purchase, the application contacts the external payment provider to authorize the transaction. If approved, the order details are written to the database. Asynchronous background jobs then process subsequent tasks, such as triggering notifications or updating seller payout balances. The final order status is persisted and can be retrieved by the buyer or seller for tracking purposes.

## 4. API architecture
The system will use a REST API, which is the decided approach for this project. This style aligns with the standard needs of a client application for product browsing, search, and transaction handling.

Key high-level operations include:
*   **Products:** Endpoints for listing, filtering, and searching items, including retrieval of associated photos.
*   **Users:** Standard authentication and account management for buyers, sellers, and administrators.
*   **Orders:** Routes to create orders, process secure card payments, and retrieve real-time status for order tracking.
*   **Seller Operations:** Specific endpoints for sellers to manage their active listings, view sales history, and handle payout requests.

Given the small team and budget, error handling will follow standard REST conventions without complex versioning strategies. The system does not currently plan to implement GraphQL or gRPC, as the simpler REST model provides sufficient structure for the defined user roles and features.

## 5. Database architecture and data model
PostgreSQL is the chosen database for this project. It stores core entities that support the e-commerce workflow and user management needs.

The primary entities include:
*   **Users:** Stores credentials and role-based access for buyers, sellers, and admins.
*   **Products:** Contains item details, descriptions, and references to stored media assets.
*   **Orders:** Records individual purchases, linking specific users to their selected products.
*   **Transactions:** Tracks payment confirmation and settlement data required for the payment provider integration.

Relationships are defined as one-to-many between sellers and their product listings, and between buyers and their respective orders. At the expected 500 peak RPS, the current data volume does not yet require sharding or specialized partitioning for performance.

Horizontal scaling is not needed, so the database architecture remains straightforward for the two-developer team to maintain.

## 6. Authentication
The specific authentication method remains unspecified, so this detail is unclear and pending confirmation. Since user accounts are required for order tracking and seller management, robust identity verification is needed for all buyer and seller roles. The admin role also requires secure access to manage the 200 active sellers and monitor site health. Because the chosen mechanism is not yet decided, all account types will rely on a future, yet-to-be-determined solution. Session or token lifetimes are not yet relevant until the core authentication strategy is finalized.

## 7. Caching
The need for a caching layer remains unclear because no specific choice was made. If implemented, it would likely store product browsing data, search results, and user session information to reduce database load. However, given the project's modest scale, this remains an open question. No specific caching technology was selected, so technical details about the caching layer are currently undefined and must be addressed later in the development cycle.

## 8. External services
This project relies primarily on an external payment provider to handle secure card transactions for buyers. This service will also manage the payouts to sellers as part of the core financial workflow. The specific vendor is not named, but the integration is essential for processing all monetary exchanges. No other external integrations were identified in the requirements. The single dependency simplifies the architecture, keeping the external interface surface area small and manageable.

## 9. Security considerations
- **Input Validation:** Strict validation is required for all user submissions, including search queries, product listings, and payment forms, to prevent injection attacks and data corruption.
- **Secrets Handling:** Private keys and API credentials for the payment provider must be stored in secure environment variables, never in configuration files or source code.
- **Access Control:** Role-based access control is essential to restrict admin functions, ensuring only staff can manage sellers, while buyers only access their own orders.
- **Data Protection:** Sensitive financial data must be encrypted in transit and at rest to comply with standard security expectations.

## 10. Scaling
The system is expected to handle up to 500 requests per second from a seller base of approximately 200 users. As horizontal scaling is not needed for this load profile, the client application will not employ distributed state across multiple nodes. Vertical scaling of individual server resources—such as CPU and memory—will be the primary mechanism for accommodating future traffic growth. The buyer count is unspecified, so long-term capacity planning remains contingent on that unknown.

## 11. Failure handling
When the external payment provider fails, transactions will be marked as pending, allowing buyers to retry later. Background job queues handle asynchronous processing; failed jobs are retried with exponential backoff before being moved to a dead-letter state. Database connections use standard timeouts to prevent thread exhaustion during PostgreSQL unavailability. No complex multi-region fallback is implemented, keeping recovery procedures simple for the two-developer team.

## 12. Trade-offs and rationale
*   **Monolith over Microservices:** A monolithic architecture is proposed (to be confirmed) because it simplifies deployment for a two-person team and fits the modest scale. Modular monolith is the alternative if code separation becomes necessary.
*   **PostgreSQL over NoSQL:** Relational integrity is prioritized over flexible schema, aligning with order and payment data requirements.
*   **REST over GraphQL:** REST is decided due to developer familiarity and simpler debugging, avoiding the complexity of GraphQL for this scope.
*   **Synchronous Core:** Core flows remain synchronous to reduce infrastructure overhead, relying only on background jobs for non-critical tasks.

## Rating (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 
