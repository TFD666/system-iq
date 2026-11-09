# Blind review: sensor_dashboard

## Design X

## 1. Architecture overview
A modular monolith architecture is optimal for this small-scope project serving approximately 50 sensors. This style minimizes operational overhead while maintaining clear internal boundaries for real-time processing. The system relies on three primary building blocks: a data ingestion layer, a state management core, and a presentation module. This structure supports immediate responsiveness for live dashboard updates without the complexity of distributed microservices.

## 2. Components and responsibilities
*   **Ingestion Service**: Connects to the external sensor infrastructure, normalizes incoming temperature and humidity samples, and pushes them into the event stream.
*   **Realtime Engine**: Consumes the data stream, maintains current sensor states in memory, and evaluates them against defined operational ranges.
*   **Alert Handler**: Triggers alert generation whenever sensor values breach configured thresholds, preparing notifications for delivery.
*   **Dashboard Interface**: Renders live metric views for staff users, consuming the current state snapshot via WebSocket or Server-Sent Events.
*   **Persistence Store**: Archives historical sensor readings for trend analysis and system auditing, decoupled from the live processing path.

## 3. Data flow
Sensor signals arrive from the external infrastructure and are immediately captured by the Ingestion Service. These raw readings enter the Realtime Engine, which updates the in-memory state map and checks for threshold violations. Simultaneously, updated states are streamed to the Dashboard Interface, ensuring staff see current values without latency. The Persistent Store receives queued data to log historical records. If a reading exceeds limits, the Alert Handler intercepts the event and dispatches a notification.

## 4. API architecture
A REST API is the most suitable style for this project. It fits well with a client application that polls for current sensor readings and subscribes to alert notifications. The API exposes a `/readings` endpoint for the latest temperature and humidity values and an `/alerts` endpoint for threshold violations. Because the system serves about 50 sensors, the workload is modest, so the API can use standard JSON payloads and simple HTTP status codes for error handling. No versioning strategy is necessary at this scale, but including a `v1` prefix leaves room for future changes without breaking the client application.

## 5. Database architecture and data model
PostgreSQL is a fitting database for this project. It reliably stores the main entities: sensors, readings, alerts, and user accounts for staff. Each sensor has many readings kept over time, and each alert references the reading that triggered it. Staff users can manage threshold configuration and receive alerts. At the scale of about 50 sensors, the data volume is small, so no partitioning or advanced indexing is required beyond a primary key on readings and foreign keys linking sensors to readings and alerts. This relational structure is straightforward to query for the live dashboard.

## 6. Authentication
Staff members must verify their identity before accessing the dashboard or configuring alert thresholds. We use OAuth 2.0 with JSON Web Tokens to secure API access between the client application and the backend. Tokens will include a standard expiration time to ensure that compromised credentials do not grant indefinite access to environmental data. This approach applies to all authenticated staff users interacting with the live readings and alert settings.

## 7. Caching
Caching is not needed for this project. The dashboard relies on a real-time data feed from approximately fifty sensors, where freshness is critical. Storing recent readings in a cache layer would introduce unnecessary complexity and potential latency for users who require immediate visibility into temperature and humidity fluctuations. We will rely on the direct WebSocket connection to push the latest data to the client application without intermediate storage delays.

## 8. External services
The system integrates with the existing sensor infrastructure to ingest temperature and humidity data continuously. This external hardware network provides the raw telemetry that drives the live dashboard displays. No other third-party cloud services or vendor-specific APIs are required for the core functionality of this project at this stage.

## 9. Security considerations
*   Input validation ensures all sensor data points fall within physically plausible ranges before storage.
*   Secrets handling stores sensor credentials and API keys in a dedicated environment variable manager, never in source code.
*   Access control restricts dashboard visibility and configuration options to authenticated staff roles only.
*   Transport layer security encrypts all data in transit between sensors, backend, and client application to prevent interception.

## 10. Scaling
With approximately 50 sensors, the system does not require complex horizontal scaling. The application server can handle initial loads on a single instance. If traffic grows, stateless API components can be replicated behind a load balancer. The database should be monitored for connection limits; read replicas can be added to offload dashboard queries from write operations. Since data volume is low, no sharding is currently necessary.

## 11. Failure handling
If the sensor infrastructure becomes unavailable, the system continues displaying last known values while marking data as stale. API calls to external services include timeouts to prevent thread blocking. Clients automatically reconnect with exponential backoff if the WebSocket connection drops. Database operations rely on transactional integrity; failed writes are logged for manual review. Alerts may be delayed during outages but are queued to fire once connectivity is restored.

## 12. Trade-offs and rationale
*   **WebSockets over polling:** Lower server overhead and real-time updates for the dashboard, at the cost of slightly more complex client-side reconnection logic.
*   **Monolithic start:** Simpler deployment for 50 sensors; microservices are deferred until actual latency or team scaling demands justify the infrastructure complexity.
*   **Client-side caching:** Reduces database load for frequently viewed historical data, accepting that stale data may appear briefly during temporary network interruptions.

## Design Y

## 1. Architecture overview
A monolith is proposed (to be confirmed) as the architecture style. This style fits the project's needs for a simple, real-time interface for warehouse staff. One key unknown is how the client application connects to the backend. A modular monolith is not chosen because it might be overkill for a system with a single user role and one main feature. The primary storage is a no-document database is proposed (to be confirmed), while a relational database is an alternative. The transmission of data to be sent is a choice yet to be made.

## 2. Components and responsibilities
- Real-time Viewer: This component shows the live temperature and humidity across the network. It handles threshold-based alerts for out-of-range readings.
- Dashboard: This component integrates with the real-time viewer.
- Data Store: This component uses a no-document database for all the data.
- Communication Server: Transmits data using websockets to the client application.

## 3. Data flow
The system receives data from fifty sensors. A request from the client application is initiated when the sensors detect a reading. This informs the communication server. The communication server writes the sensor readings to a no-document database. 

A websockets connection provides the real-time data to the client application. A request initiates when the client application attempts a no-document database write. A sensor alert occurs when any of the thresholds are exceeded.

## 4. API architecture
The project proposes using a REST API, though this decision is proposed (to be confirmed) pending final requirements review. gRPC remains an alternative. High-level operations will include retrieving current sensor readings and managing alert thresholds. Real-time data delivery will rely on a WebSocket connection, a choice also proposed (to be confirmed) over server-sent events. As specific request rates are unspecified, complex versioning or extensive error-handling protocols are not yet defined.

## 5. Database architecture and data model
A NoSQL database, likely DynamoDB, is proposed (to be confirmed) for storage, with PostgreSQL as an alternative. The system will store main entities: sensor definitions and time-stamped readings (temperature and humidity). Readings will link to specific sensors, forming a one-to-many relationship. Since the client application type and exact data retention periods remain unspecified, the final indexing strategy and exact schema structure require further analysis to align with the specific query patterns of warehouse staff.

## 6. Authentication
The authentication approach has not yet been decided, as it remains an open requirement not specified in the project data. Consequently, the specific method for verifying user identity—such as token-based or session-based mechanisms—is unclear. Because the client application platform was not specified, the compatibility of potential authentication schemes with the specific interface remains an unresolved design question. Until these unknowns are addressed, no statement can be made regarding how warehouse staff will securely access the real-time display functionalities for environmental monitoring.

## 7. Caching
Whether a caching layer is needed for this project is unclarified, meaning the decision remains uncertain. The rationale typically centers on whether it would cache frequent reads of current environmental states or threshold configurations from the storage layer. However, because the specific caching layer choice has not been determined and the need itself is uncertain, no concrete implementation is proposed. This pending decision relies on further clarification of performance requirements to determine if caching infrastructure is necessary.

## 8. External services
The project depends on a sensor network integration. This external service is used to provide real-time streams of temperature and humidity data from the fifty designated physical sensors. No other external services or third-party integrations were specified in the project data. Additional integrations might be considered later for alert delivery or historical data analysis, but current dependencies are limited strictly to the incoming sensor data feed.

## 9. Security considerations
-   Input validation must strictly verify numeric ranges for sensor data to prevent injection or logical errors.
-   Secrets handling for the sensor network credentials must use environment variables or a dedicated secrets manager, never hardcoding.
-   Access control is not yet decided, but it must ultimately restrict dashboard access to the defined warehouse staff role.
-   Real-time data streams should be encrypted in transit to prevent interception or tampering of environmental readings.

## 10. Scaling
The system is designed for a specific input load from fifty sensors. Horizontal scaling is not needed, so the architecture supports initial growth without horizontal distribution. Adding new sensor groups may require storage expansion rather than spreading application state across a fleet of servers. Capacity for concurrent users is unspecified, so performance under peak user load is unclear. The system relies on efficient data handling to support the real time stream and threshold logic, with future needs to be verified against specific scaling targets as they become known.

## 11. Failure handling
When a sensor stream is interrupted, the system detects missing readings and continues monitoring other sensors without stopping. The network may retry connections with timeouts if they are unavailable, but this strategy is not yet decided. Alert delivery failures might require fallback mechanisms to signal broken channels, though the delivery method remains unspecified. If storage is unavailable, the application can buffer incoming data temporarily. Overall resilience relies on the service being stateless. Data retention requirements are unknown, limiting how prolonged failures can be fully isolated.

## 12. Trade-offs and rationale
- A monolith is selected for simpler deployment because the distributed alternative is proposed.
- WebSocket is favored for low latency, though server-sent events are proposed.
- DynamoDB is chosen for stream handling, yet PostgreSQL is an alternative for retrieval.
- RESTful design provides flexibility, though the selection is still tentative and complex.
- Unclear requirements leave specific tuning for the caching layer pending decision.

## Rating (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 
