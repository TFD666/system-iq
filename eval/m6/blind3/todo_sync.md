# Blind review round 2 (three arms): todo_sync

## Design X

## 1. Architecture overview
A monolithic architecture is adopted for this project. This style provides operational simplicity for a system serving 10,000 users without the overhead of distributed systems. The single deployable unit encompasses all business logic, data access, and API endpoints. This design effectively supports offline-first capabilities and cross-device synchronization. The system relies on asynchronous processing to handle collaborative tasks. No additional caching layers are introduced to maintain a straightforward deployment footprint. Horizontal scaling is not required to meet the specified usage volume.

## 2. Components and responsibilities
- **API Gateway:** Manages RESTful endpoints for authentication, data retrieval, and synchronization requests.
- **Core Business Logic:** Handles to-do list creation, editing, and sharing policies between registered users.
- **Data Access Layer:** Interfaces with the PostgreSQL database to persist user accounts and list states.
- **Synchronization Engine:** Reconciles local device data with server-side records upon connectivity.
- **Async Worker:** Processes background tasks for list sharing notifications and state propagation.

## 3. Data flow
The client application initiates a REST request to the API Gateway for synchronization. The gateway authenticates the user and forwards the payload to the Core Business Logic. Data is fetched from PostgreSQL to compare local and remote states. Write operations are persisted to the database immediately. Share requests trigger the Async Worker to process recipient updates. The final state is serialized and returned to the client for offline storage. No external caches or integrations influence this cycle.

## 4. API architecture
REST fits this system because stateless JSON endpoints simplify the client application’s offline logic and sync workflows.

Main resources include:
- `POST /sync` to upload pending local changes
- `GET /sync` to retrieve remote updates since the last checkpoint
- `POST /lists` to create shared to-do lists
- `PATCH /items/{id}` to modify individual tasks
- `GET /lists/{id}/share` to manage access permissions for family members

Versioning uses URI path prefixes, starting with `/v1/`. Error responses follow standard HTTP status codes with structured JSON bodies detailing validation failures or conflict states.

## 5. Database architecture and data model
PostgreSQL serves as the primary database, offering robust relational integrity and JSONB support for flexible task metadata.

Core entities include:
- Users: account identifiers and authentication details
- Lists: title, visibility, and associated user IDs
- Items: task description, status, and priority
- ShareRequests: records of list-sharing permissions

Each Item belongs to one List, which many-to-many links with Users via membership tables. The system uses unique constraints on user-list pairs to prevent duplicate entries. No partitioning is required given the moderate scale of 10,000 users.

## 6. Authentication
The client application enforces mandatory user accounts to facilitate cross-device synchronization and list sharing. Authentication utilizes JWT-based token verification via REST endpoints, granting access exclusively to End User roles. Tokens persist for a duration sufficient to maintain seamless offline transitions, allowing the client to cache credentials before connectivity is restored.

## 7. Caching
Caching is not needed. The monolithic architecture directly queries the primary database for all read and write operations. Without specific performance bottlenecks identified regarding concurrency or latency, an additional caching layer would introduce unnecessary complexity and maintenance overhead for this scale.

## 8. External services
The project requires zero external services or integrations. All core functionalities, including offline storage, synchronization, and sharing, are handled entirely within the internal monolithic application. Data persistence relies solely on the internal primary database, eliminating third-party dependencies for core business logic.

## 9. Security considerations
*   **Input Validation:** Implement strict schema validation on all REST endpoints to prevent injection attacks and ensure data integrity during synchronization.
*   **Secrets Handling:** Store encryption keys and database credentials in a localized environment secret manager, never embedded in the client application or source code.
*   **Access Control:** Enforce role-based permissions via JWT claims to ensure users can only access or modify their own to-do lists and shared family members’ data.

## 10. Scaling
The system is designed as a monolith to handle the projected load efficiently without unnecessary complexity. Since horizontal scaling is not required for this project, the application server runs as a single instance. The stateless REST API allows for straightforward vertical scaling if user activity increases. Data storage relies on a single primary database, ensuring simple maintenance and data consistency for the ten-thousand user base. This vertical-first approach minimizes infrastructure overhead and keeps operational costs low while meeting current demand projections.

## 11. Failure handling
If the primary database becomes unavailable, the system relies on client-side offline storage to maintain data integrity. API requests will encounter standard timeout mechanisms, prompting the client application to queue synchronization tasks for later execution. There are no external dependencies to fall back on. Transient network errors trigger automatic retries with exponential backoff to recover connectivity. If a server component fails, users simply remain in offline mode until the service restores full functionality.

## 12. Trade-offs and rationale
- **Monolith over microservices**: A single codebase simplifies deployment and debugging for a team of this size.
- **No caching layer**: With modest scale, database query performance remains sufficient, reducing infrastructure complexity.
- **Offline-first data model**: Prioritizes local storage to ensure data availability without network access.
- **REST over WebSockets**: Standard HTTP methods facilitate easier caching by intermediaries and simpler client implementation.
- **No horizontal scaling**: Accepts single-node limits to avoid distributed system complexities like sharding or replication.

## Rating: Design X (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 

## Design Y

## 1. Architecture overview
The system follows a modular monolith architecture, which is appropriate for this project’s scope and team size. This approach allows independent scaling of sync, authentication, and sharing modules while maintaining a single deployable unit. The main building blocks are a REST/GraphQL API server, a relational database, and a background job worker handling sync conflicts and notifications. A lightweight GraphQL gateway sits in front of the API server to simplify client queries across multiple domains.

## 2. Components and responsibilities
- **Client Application**: Manages local to-do lists, caches data for offline operation, and triggers sync when connectivity is restored.
- **API Gateway**: Routes all client requests, enforces authentication, and load-balances requests to the backend services.
- **User & Family Service**: Manages user accounts, family group memberships, and access permissions for list sharing.
- **Task Service**: Owns to-do list and item CRUD operations, including offline conflict detection logic.
- **Sync Service**: Handles bidirectional data reconciliation between devices when online, resolving conflicting updates.
- **Relational Database**: Stores persistent user, list, and task data.

## 3. Data flow
A user opens the client application in offline mode to view cached to-do lists. Upon regaining connectivity, the client application submits pending changes to the Sync Service. The service reads the latest state from the Relational Database, applies conflict resolution rules, and writes updates. If a user shares a list, the User & Family Service updates membership records. Subsequent syncs propagate these changes to all linked family devices.

## 4. API architecture
A RESTful API style is adopted because it simplifies client implementation for standard CRUD operations and plays well with HTTP caching for offline storage. The backend exposes resources for lists, tasks, and sharing permissions, allowing the client application to fetch, create, update, and delete data independently. Each list entity includes metadata for family access control, while tasks are nested under their parent list. Basic state management relies on versioning numbers; clients compare local task versions to detect conflicts during synchronization when the client application reconnects. Error responses follow standard HTTP status codes, using 409 specifically for sync conflicts to guide client-side merge logic without complex custom protocols.

## 5. Database architecture and data model
PostgreSQL is selected for its robust JSONB support, which accommodates flexible task attributes without frequent schema migrations. The data model centers on three entities: Users, Lists, and Tasks. Users link to Lists through a many-to-many relationship to support family sharing, mediated by a ListMembers join table that stores role permissions. Each List contains multiple Tasks, forming a one-to-many relationship. For scale targets of 10,000 users, standard B-tree indexes on list IDs and user IDs suffice without requiring partitioning. A unique constraint ensures list ownership integrity, while a full-text search index may be added later if search requirements are defined. Data volume remains unspecified, so no specific sharding strategy is implemented initially.

## 6. Authentication
Users and Family Members access the platform via secure server-side session tokens. Each authenticated device receives a unique identifier allowing it to fetch and push changes to cloud storage only for lists it owns or has been granted explicit permission to view. To protect user privacy on shared hardware, the client application revokes access when a user logs out, ensuring that residual local data remains encrypted until the next successful credential verification. No additional third-party identity providers are integrated into this design.

## 7. Caching
Local caching is essential to satisfy the offline operation requirement. The client application maintains a persistent, encrypted SQLite database that stores the complete graph of lists, tasks, and ownership relationships. This local cache serves as the source of truth when the network is unavailable. When connectivity is restored, a background synchronization service calculates the delta against the cloud backend, applies remote modifications in a conflict-free manner, and pushes pending local updates. This effective caching layer eliminates the need for separate in-memory server-side caching in this design.

## 8. External services
This project does not depend on any external services or integrations. All core functionality, including offline task management and online data synchronization, is delivered by the in-house backend infrastructure. No third-party communication pipelines, authentication providers, or payment gateways are required. The cloud backend acts as the sole dependency, managing the persistent state and coordination logic required to keep multiple client applications in sync. This self-contained architecture simplifies maintenance and reduces third-party integration complexity.

## 9. Security considerations
*   The backend automatically rejects and sanitizes any unsanitized user input prior to database persistence, effectively mitigating injection-based vulnerabilities across all API endpoints.
*   Server-side secrets and cryptographic keys are isolated within environment variables, preventing direct access via configuration repositories or executable code.
*   Server-side authorization logic strictly validates ownership and sharing privileges before processing every API request, ensuring that Family Members cannot exceed the access boundaries granted by the primary User.
*   Sensitive tokens stored via local caching are encrypted using the platform’s secure hardware keystore, preventing unauthorized extraction from device memory.

## 10. Scaling
The system targets approximately 10,000 users, which fits comfortably within a horizontally scalable distributed backend. A relational database handles metadata, while separate service instances manage sync logic. As traffic increases, horizontal scaling adds compute nodes behind a load balancer. Stateless API servers allow dynamic capacity adjustments. Data partitioning by user ID ensures linear growth in storage and processing. No sharding is required for the current user base, but the architecture supports it if user counts grow significantly.

## 11. Failure handling
The client application operates fully offline, ensuring task management continues during network outages. When back online, the client attempts to sync pending changes. The backend uses retry logic with exponential backoff for temporary network issues. Timeouts prevent indefinite hangs during sync operations. If the database is unavailable, the API returns a temporary failure code, prompting the client to cache changes locally. No fallback mechanisms are needed for core data integrity, as the design prioritizes eventual consistency over immediate availability.

## 12. Trade-offs and rationale
*   **Cloud sync over direct sync:** Chosen for simplified infrastructure and robust security, despite higher latency than peer-to-peer options.
*   **Eventual consistency:** Accepts minor delays in cross-device updates to enable reliable offline functionality and reduce complex conflict resolution overhead.
*   **Relational database:** Selected for strong data consistency in list structures, rather than NoSQL, due to structured share relationships.
*   **No external integrations:** Keeps the attack surface small and reduces vendor lock-in, aligning with the focus on core list management features.

## Rating: Design Y (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 

## Design Z

## 1. Architecture overview
The system uses a modular monolith approach, a proposal to be confirmed over a standard monolith. This style suits the single-team scope of a to-do application serving 10,000 users. Horizontal scaling is not needed, allowing a focused deployment. The main building blocks are a client application for offline-first interaction and a server-side module handling authentication, synchronization, and sharing permissions. These components work together to ensure data consistency across devices whenever network connectivity is available.

## 2. Components and responsibilities
- **Client Application:** Manages local offline storage, tracks to-do list state, and detects network availability to trigger sync operations.
- **Authentication Service:** Verifies user and family member identities to securely link accounts and validate access to shared resources.
- **Sync Engine:** Reconciles local changes with server data, resolving conflicts to maintain a consistent view of lists across all connected devices.
- **Sharing Module:** Controls permissions for list access, ensuring family members can only view or modify lists they are explicitly authorized to share.

## 3. Data flow
A user modifies a to-do item in the client application, which saves the change locally for immediate offline availability. When connectivity is detected, the client sends the update to the server via a REST API. The server authenticates the request, checks sharing permissions, and writes the new state to the primary database. PostgreSQL is proposed (to be confirmed) as the primary store, with MongoDB as an alternative. Upon successful persistence, the server confirms the sync, allowing other family devices to retrieve the latest version.

## 4. API architecture
The system will use a REST API. This style is a decided choice because it fits the straightforward retrieval and modification of to-do lists and user accounts. Main endpoints will handle creating and listing tasks, managing user profiles, and assigning sharing permissions for family members. JSON will be the standard format for request and response bodies. Specific details for error handling syntax are not yet decided, as the broader architecture is proposed (to be confirmed).

## 5. Database architecture and data model
The primary database is proposed (to be confirmed) as PostgreSQL, with MongoDB listed as an alternative. It must store core entities including Users, Lists, and Tasks. Relationships involve links between users and the lists they own or access, connecting lists to their constituent tasks, and mapping permissions for family members. Indexing or partitioning is not needed at this time, as the expected scale of 10,000 users does not currently suggest high-level data volume requirements.

## 6. Authentication
User authentication is required to link accounts for device synchronization and list sharing across family members. The specific authentication method was not specified in the requirements, so it remains unclear which protocol (e.g., OAuth2, JWT) will be implemented. It will apply to both regular users and family members accessing shared content. Session or token lifetime details have not been defined yet.

## 7. Caching
It is unclear whether a dedicated caching layer is needed. Peak request rates and specific performance targets were not provided in the initial scope, making it difficult to determine if performance gains justify the added complexity. No specific caching technology has been chosen yet. The decision will depend on clarifying the expected load profile during the next review phase.

## 8. External services
No external services or integrations were listed in the requirements. The project relies on internal components for database storage and API communication. There are no specified dependencies on third-party payment gateways, real-time messaging providers, or media storage platforms. The focus remains on internal data management and cross-device synchronization using standard web technologies.

## 9. Security considerations
- Input validation must enforce strict checks on all API endpoints to prevent injection attacks.
- Secrets handling should use environment variables or a dedicated secrets manager, never hard-coded values.
- Access control mechanisms must distinguish between regular users and family members, ensuring users can only access lists explicitly shared with them.
- Data in transit needs encryption using TLS, and stored credentials must be hashed securely.

## 10. Scaling
The system anticipates approximately 10,000 users. Given the expected scale, horizontal scaling was decided not to be required. Consequently, the architecture relies on vertical scaling capabilities inherent to a server-side deployment. If future traffic exceeds initial estimates, the team must reassess capacity planning. Currently, no specific mechanisms for distributed load balancing are mandated by the requirements. The backend can be deployed on a single scalable instance or a small cluster.

## 11. Failure handling
Not yet decided how failures will be managed. The need for asynchronous processing is unclear, meaning background queues may not exist to buffer errors. Since caching is also uncertain, direct database calls will handle most requests. No specific retry or timeout strategies are defined in the current data. The client application operates offline, which provides a natural fallback for server unavailability. Users will continue working locally, syncing data whenever connectivity is restored to the server.

## 12. Trade-offs and rationale
- A modular monolith is proposed (to be confirmed) to balance complexity against the smaller user base, avoiding the overhead of microservices.
- REST is accepted for API communication due to its simplicity, though GraphQL remains a low-probability alternative.
- The primary database choice is undecided; PostgreSQL is proposed (to be confirmed) versus MongoDB, depending on final data modeling needs.
- No dedicated caching layer is specified, accepting slightly higher database load in exchange for simpler infrastructure management.

## Rating: Design Z (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 
