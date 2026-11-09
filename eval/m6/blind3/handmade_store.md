# Blind review round 2 (three arms): handmade_store

## Design X

## 1. Architecture overview
The system uses a monolith architecture, chosen to fit the project's small budget and two-developer team. This style suits the expected scale of about 200 sellers and a peak load of 500 requests per second. The main building blocks are a single API service, a PostgreSQL database, and a background job processor for asynchronous tasks.

## 2. Components and responsibilities
- API Service: Handles all REST requests for product catalog, search, orders, and user management.
- Authentication Module: Manages buyer and seller accounts using explicit user credentials.
- Payment Integration: Interacts with the external payment provider for card transactions.
- Background Processor: Executes non-blocking tasks like seller payouts and order status updates.
- Media Storage: Stores and serves product photos; the specific implementation is not yet decided.
- Database Layer: Persists all core data in a single PostgreSQL instance.

## 3. Data flow
A buyer searches the catalog, triggering a query to the PostgreSQL database. When a purchase is made, the client application sends payment details. The system validates the transaction via the payment provider integration. If successful, the order is written to the database. Concurrently, a background job processor is notified to handle seller payouts and order tracking updates asynchronously.

## 4. API architecture
REST was selected as the API style, fitting the project’s straightforward data retrieval and transactional needs. Key operations include product catalog retrieval, search filtering, order creation, and payment processing. Since the team consists of only two developers working with a small budget, a REST approach minimizes implementation complexity compared to GraphQL. Error handling follows standard HTTP status codes to clearly distinguish between client errors and server faults. While versioning is not yet decided, it may become relevant if the client application undergoes significant API changes in the future. The choice supports the required integration with an external payment provider through well-defined endpoint contracts.

## 5. Database architecture and data model
PostgreSQL was chosen to store the project’s core data. Main entities include Products, Sellers, Users, Orders, and Payments. Relationships connect Sellers to their Product listings, Users to their Orders, and Orders to corresponding Payment records. Given the expected scale of about 200 sellers and 500 peak requests per second, advanced partitioning is not needed. However, indices on product categories and order status will support efficient search and order tracking queries. This relational structure ensures data integrity for financial transactions while remaining manageable for a small development team.

## 6. Authentication
The project needs explicit user accounts to manage listings and track orders for both buyers and sellers. The specific authentication mechanism is not yet decided because the requirement remains unspecified. Consequently, details regarding session or token lifetimes are currently undetermined. Once the method is confirmed, it will secure access to all role-specific features.

## 7. Caching
The need for a caching layer is unclear. No specific caching technology has been chosen for this project. The decision depends on further analysis of performance requirements, which are not fully defined. Consequently, no cache implementation is currently specified. This remains an open question pending design review.

## 8. External services
The project relies on an external payment provider to handle card transactions and seller payouts. This service manages secure financial processing for the marketplace. No other external integrations are specified in the current requirements. All other functionality is expected to be handled internally by the client application.

## 9. Security considerations
- Input validation protects against malicious data in product forms and search queries.
- Secrets handling ensures payment credentials are stored securely on the server.
- Access control enforces role-based permissions for buyers versus sellers.
- The system validates order tracking requests to prevent unauthorized data access.
- Regular security audits are required due to the small development team.

## 10. Scaling
The system relies on vertical scaling rather than horizontal scaling, as it was decided that horizontal scaling is not needed to handle the expected load. With a modest user base of about 200 sellers and a peak of 500 requests per second, a single server instance can support the current traffic. The monolithic architecture simplifies deployment and maintenance, aligning with the constraint of only two developers. If traffic increases significantly in the future, the application can be scaled vertically by upgrading hardware resources. No complex load balancing or distributed state management is required at this stage.

## 11. Failure handling
If a dependency such as the payment provider fails, the client application should display an error message to the user and retry the request. Timeouts should be configured to prevent indefinite hangs. Since the system uses PostgreSQL, database connectivity issues should trigger failover or retry mechanisms if replication is set up. Background jobs for asynchronous processing can be re-queued if they fail. The design does not specify complex fallback services, so basic error handling and user notification are the primary strategies for managing component failures.

## 12. Trade-offs and rationale
- **Monolith over microservices:** Chosen to reduce complexity and development overhead, fitting the small team size.
- **REST over GraphQL:** Selected for its simplicity and lower implementation cost, suitable for the defined features.
- **PostgreSQL over MongoDB:** Preferred for strong relational consistency in user, product, and order data.
- **No horizontal scaling:** Avoided to simplify operations, as current load is low.
- **Uncertain caching:** Deferred until performance metrics justify the added infrastructure cost.

## Rating: Design X (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 

## Design Y

## 1. Architecture overview
A modular monolith is the optimal style for this project. With only two developers and a small budget, microservices would introduce unnecessary operational complexity and communication overhead. The single deployable unit allows for simple local development and easy scaling within the current traffic limits. The system comprises a client application, a central API server, a relational database, and external media and payment services. This structure supports the required buyer and seller functionalities while maintaining code cohesion and minimizing infrastructure costs.

## 2. Components and responsibilities
*   **Client Application:** Manages user interface interactions for browsing, searching, checkout flows, and seller dashboard operations.
*   **API Server:** Handles all business logic, including product categorization, cart management, order processing, and role-based access control.
*   **Relational Database:** Stores product records, user credentials, user-specific role flags, order histories, and transaction statuses.
*   **Media Storage Service:** Hosts and serves product photography, removing binary blob storage burdens from the primary database.
*   **Payment Provider Integration:** Executes card payments and initiates seller payout processing via a secure, third-party gateway.

## 3. Data flow
A buyer initiates a search, prompting the client application to send a request to the API server. The API server queries the relational database for matching product records and returns the serialized data, which includes media URLs. Upon checkout, the client sends payment details via the API server to the external payment provider. Once the provider confirms the transaction, the API server writes the order details and status to the database. The client then polls for order status updates, reading from the database via the API to track fulfillment progress.

## 4. API architecture
A RESTful API is appropriate because it aligns with the two-developer team size and the simple, resource-oriented nature of the marketplace. Primary operations include:
- `GET /products`: List items with search and filter parameters.
- `POST /products`: Create seller listings with photo metadata.
- `POST /orders`: Initiate card payments via the payment provider.
- `GET /orders/{id}`: Track order status and payout details.
Requests are authenticated via bearer tokens to distinguish buyer and seller roles. Errors follow standard HTTP status codes with JSON bodies containing descriptive messages, reducing client-side parsing complexity.

## 5. Database architecture and data model
PostgreSQL stores the core relational data, ensuring ACID compliance for financial transactions. Key entities include:
- **Users**: Stores authentication credentials and role flags (buyer/seller).
- **Products**: Links to sellers, includes title, price, and photo URLs.
- **Orders**: Records transactions, status, and timestamps.
- **Payouts**: Tracks seller earnings linked to completed orders.

Sellers have one-to-many relationships with both products and payouts. Buyers have one-to-many relationships with orders. A single index on `products.created_at` supports the peak of 500 requests per second without requiring partitioning.

## 6. Authentication
User authentication is required to distinguish between Buyer and Seller roles, thereby controlling access to listing and payout management features. The client application will utilize a standard session or token mechanism to maintain user state securely. This approach directly addresses the core requirement of role-based access without incurring the operational overhead of complex third-party identity providers, keeping infrastructure costs aligned with the small budget.

## 7. Caching
Caching is required to manage the peak load of 500 requests per second. We will implement an in-memory data grid to store frequently accessed product listings and search results. This layer will reduce the pressure on the primary database during high-traffic search events. It also serves as a simple, cost-effective solution that allows two developers to maintain high performance without adding complex infrastructure maintenance scripts.

## 8. External services
The system relies on a generic payment processing service to handle card transactions for purchases and financial payouts for sellers. This external service processes financial instruments securely and returns status updates to the application backend. Additionally, a secure digital object store is required to host high-resolution product photos for buyer browsing. This separation ensures that media assets do not consume excessive backend storage resources and facilitates faster image loading.

## 9. Security considerations
*   **Input Validation**: All search queries, filter parameters, and listing submissions will be strictly validated against defined schemas to prevent injection attacks and data corruption.
*   **Secrets Handling**: API keys for the payment provider and media storage must be stored in an isolated secrets manager, never in application code or local configuration files.
*   **Access Control**: Middleware will verify user roles on every request, ensuring buyers can only view listings while sellers can manage their own inventory and access financial details.
*   **Data Protection**: Passwords and sensitive financial data will be encrypted at rest and in transit using industry-standard protocols.

## 10. Scaling
The system is designed for approximately 200 sellers and 500 peak requests per second. Given the small team and budget, a single-tier monolithic architecture is appropriate initially. Horizontal scaling can be added later by placing a load balancer in front of multiple application instances if traffic exceeds current capacity. Database read replicas may be introduced for search-heavy workloads if necessary, but this is not required at the current scale.

## 11. Failure handling
Payment provider timeouts trigger automatic retries with exponential backoff. Failed payments leave orders in a "pending" state rather than being deleted. If the database becomes unavailable, the application returns a 503 error to clients. No complex fallback mechanisms are implemented due to the small team size; instead, clear error messages guide users and alert the development team for manual intervention.

## 12. Trade-offs and rationale
- **Monolith over microservices:** Reduces operational complexity and infrastructure costs, aligning with the two-developer team and small budget.
- **No specialized search engine:** Standard database queries handle filtering, avoiding the complexity of managing Elasticsearch or similar tools.
- **Basic monitoring:** Simple logging and uptime checks replace sophisticated observability platforms, keeping overhead low while maintaining visibility into system health.

## Rating: Design Y (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 

## Design Z

## 1. Architecture overview
We adopt a monolith because 200 sellers and a modest team of two developers make distributed complexity unnecessary and unsustainable. A single deployable unit simplifies operations, reduces infrastructure costs, and allows one codebase to own all core features. The main building blocks are a REST API layer, a PostgreSQL database, an in-memory cache, and an async task queue for background jobs like payout processing. This structure supports 500 peak requests per second without horizontal scaling, keeping the system simple, maintainable, and aligned with the small budget constraint. All business logic for browsing, orders, listings, and payouts lives within this unified application.

## 2. Components and responsibilities
- **REST API**: Exposes all buyer and seller endpoints for browsing, search, orders, listings, and payout management.
- **Product & Search Service**: Handles product indexing, filtered search queries, and real-time availability checks.
- **Order Management**: Processes order creation, status transitions, and tracking updates for both roles.
- **Seller Operations**: Manages listing CRUD, user verification workflows, and inventory records.
- **Payout Engine**: Calculates and records seller earnings, triggering external payment provider calls.
- **Async Worker**: Processes non-blocking tasks like payout notifications and order finalization in the background.
- **Cache Layer**: Serves frequent product and user data to reduce database load during peak traffic.

## 3. Data flow
A client application sends a REST request to the API layer, which first checks the cache for product or user data. Cache misses trigger a read from PostgreSQL. For write operations like placing an order, the API validates input, writes the order record to the database, and updates the cache. If the action requires a payout or notification, the API publishes a job to the async queue. The worker processes this job, calls the external payment provider, and updates the database with the final status. This flow ensures fast reads, consistent writes, and deferred external calls.

## 4. API architecture
We adopt a RESTful style for the API, fitting the straightforward request-response nature of product search and order tracking. Key endpoints include `GET /products` with filter parameters for search, `POST /orders` to create transactions, and `GET /orders/{id}` for status updates. Seller management endpoints handle listing creation and payout requests, routed through strict role-based access checks. Error responses follow standard HTTP conventions with JSON payloads describing specific validation or authorization failures. API versioning is omitted initially due to the small team size, relying instead on internal consistency. This approach simplifies caching strategies and client implementation while supporting the integration with the external payment provider.

## 5. Database architecture and data model
PostgreSQL serves as the primary relational database, storing core entities: Users, Products, Orders, and Payouts. Users connect to Orders via a foreign key, distinguishing buyers from sellers by role. Products link to Sellers, while Orders contain line items referencing specific Product IDs. Payouts record financial settlements linked to completed Orders and specific Sellers. We implement standard B-tree indexes on frequently queried fields, such as Order status and Product categories, to optimize search performance. No partitioning is required given the modest data volume and single-node deployment. This normalized structure ensures data integrity for financial transactions and simplifies reporting for seller-specific queries.

## 6. Authentication
The system implements JSON Web Token (JWT) authentication for both buyers and sellers. This stateless approach simplifies session management within the monolithic architecture and supports role-based access control. Tokens include role claims to distinguish between buyer and seller privileges. Token expiration is set to enforce periodic re-authentication, enhancing account security without requiring complex server-side session storage.

## 7. Caching
Redis is integrated as the primary caching layer to reduce database load during product browsing and search operations. It caches frequently accessed product details, search results, and seller profiles. This layer improves response times for high-traffic read paths, particularly at 500 requests per second. Cache invalidation is triggered whenever product or seller data is updated in the primary database.

## 8. External services
The project depends on a payment provider integration to process buyer transactions and manage seller payouts. This service handles payment authorization, capture, and settlement processing. It is the sole external dependency, ensuring the system remains self-contained for all other operational needs, including user verification and order management.

## 9. Security considerations
- **Input validation:** All API inputs are strictly validated to prevent injection attacks and data integrity issues.
- **Secrets handling:** Credentials for the payment provider are stored in environment variables, never in code or configuration files.
- **Access control:** Role-based checks enforce that buyers cannot access seller endpoints and vice versa, protecting sensitive financial data.
- **Data encryption:** Sensitive user and payment data is encrypted at rest and in transit using TLS.

## 10. Scaling
The monolithic architecture is deployed on a single server instance to keep operational costs minimal for the two-person development team. At the projected peak of 500 requests per second and 200 active sellers, the system operates well within standard hardware limits without requiring cluster rotation.

*   **Vertical scaling:** Increase CPU and memory on the primary host as user volume grows.
*   **Connection pooling:** PostgreSQL uses connection limits to manage simultaneous database sessions efficiently.
*   **No horizontal load balancing:** Omit distributed layer to reduce infrastructure complexity and maintenance overhead.

## 11. Failure handling
The system relies on simple timeout management and manual notification for external dependencies. If the payment provider becomes unavailable, the client application displays a generic error state, and the order remains in a "pending" status. Developers can manually retry failed transactions via an administrative console later.

*   **Payment timeouts:** Requests to the payment provider fail after a fixed duration, preventing thread blockage.
*   **Database isolation:** PostgreSQL transactions rollback if a concurrent error occurs, ensuring data integrity.
*   **Cache resilience:** If the cache layer fails, the system falls back to direct database queries, slightly increasing latency.

## 12. Trade-offs and rationale
*   **Monolith over Microservices:** A single codebase simplifies deployment and debugging, saving the two developers from managing complex service orchestration and network latency.
*   **PostgreSQL over NoSQL:** Relational integrity is essential for accurate order tracking and financial payouts, despite higher write latency for simple reads.
*   **No horizontal scaling:** Accepting a single-point-of-failure risk is justified by the low expected scale and strict budget constraints.
*   **Manual fallbacks:** Automated retry logic is omitted to reduce code complexity, as volume is low enough for human intervention.

## Rating: Design Z (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 
