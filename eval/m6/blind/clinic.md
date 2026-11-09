# Blind review: clinic

## Design X

## 1. Architecture overview
This project utilizes a modular monolith architecture. This style provides manageable deployment complexity while isolating domain logic, which is optimal for a system serving 305 users. It avoids the operational overhead of microservices without sacrificing maintainability. The main building blocks include an identity module for authentication, a scheduling core for availability, and a notification gateway for external messaging.

## 2. Components and responsibilities
-   **Identity Service:** Manages patient and doctor registration, login state, and role-based access control.
-   **Scheduling Core:** Stores daily doctor schedules and processes appointment requests, ensuring slot contention is handled atomically.
-   **Notification Gateway:** Interfaces with external email and SMS providers to dispatch appointment confirmation and reminder messages.
-   **API Interface:** Serves as the single entry point for all web client requests, routing them to internal modules.

## 3. Data flow
A logged-in patient initiates a booking request via the web interface. The API validates the user session and forwards the request to the Scheduling Core. This component reads the doctor’s available slots from the database and checks for conflicts. Upon a successful check, it writes the new appointment record to the persistence layer. Finally, the Scheduling Core triggers the Notification Gateway to send confirmation messages through the external providers.

## 4. API architecture
We adopt REST because it aligns with the straightforward CRUD operations of booking and scheduling. Key endpoints handle appointment creation, availability queries, and schedule updates. Role-based access control ensures patients and doctors access only relevant data. Error responses follow standard HTTP status codes with descriptive messages for validation failures or authorization errors. This approach simplifies client integration and debugging without the complexity of real-time protocols.

## 5. Database architecture and data model
We select PostgreSQL for its robust relational integrity and JSONB support for flexible metadata. Core entities include Patients, Doctors, Appointments, and Schedules. Patients link to Appointments in a one-to-many relationship. Doctors manage Schedules, which define recurring availability slots. Appointments reference both Patient and Doctor IDs to maintain referential integrity. No partitioning is required at the current scale of 305 users. Standard B-tree indexes on appointment timestamps and user identifiers optimize query performance for availability checks.

## 6. Authentication
All users, both patients and doctors, will use a unified identity provider based on OAuth 2.0. This approach ensures secure credential management and simplifies integration with external services. The system will issue short-lived JSON Web Tokens for API access, requiring re-authentication for sensitive actions. This applies to all role-based actions, ensuring that patients can only book appointments while doctors can manage schedules and view patient data.

## 7. Caching
Redis will be utilized to cache frequent lookups, such as doctor availability and user session data. This reduces database load during peak booking times and accelerates response times for schedule checks. User-specific data, including authentication tokens and profile information, will also be cached. This layer addresses the need for rapid access to dynamic scheduling information, ensuring a smooth user experience during high-traffic periods.

## 8. External services
The system relies on an email provider service. This service handles all transactional email notifications for appointment confirmations and reminders. It also integrates with an SMS provider service. This service delivers text message notifications to users who have opted in for SMS alerts. Both services are abstracted behind internal interfaces, allowing for easy configuration and provider management without altering core application logic.

## 9. Security considerations
- Input validation: All API inputs are strictly validated to prevent injection attacks and data corruption.
- Secrets handling: API keys for email and SMS providers are stored in an environment variable manager, never in code.
- Access control: Role-based access control ensures patients cannot modify doctor schedules, and doctors cannot view unrelated patient records.
- Data encryption: Sensitive patient health data is encrypted at rest and in transit using industry-standard protocols.

## 10. Scaling
The system is designed for 305 users, which does not require complex horizontal scaling. A single application server instance serves sufficient traffic for this user base. The database operates on a single node due to minimal concurrent load. If future growth exceeds current projections, the architecture permits adding application servers behind a load balancer. This modular approach ensures linear capacity increases without re-architecting the core services. No specific peak requests per second are defined, so scaling thresholds remain advisory.

## 11. Failure handling
The application ensures availability through straightforward failure management. Email and SMS providers operate as external dependencies with defined timeout limits. If a notification provider fails, the system logs the error and retries the delivery process with exponential backoff. Patients receive failed notifications via alternative channels if possible, or the failure is exposed to administrators for manual intervention. The database includes automatic replication to prevent data loss during hardware failures, ensuring appointment records remain consistent and accessible during recovery periods.

## 12. Trade-offs and rationale
-   **Monolithic Architecture:** Prioritizes development speed and lower operational complexity over microservices, suitable for 305 users.
-   **Synchronous Notifications:** Simplifies state management compared to asynchronous queues, accepting potential latency during provider outages.
-   **Standard Authentication:** Avoids custom security solutions, relying on established libraries to mitigate risk and reduce development time.
-   **Single Database Node:** Eliminates distributed data consistency challenges, trading off geographic redundancy for data integrity and simplicity.

## Design Y

## 1. Architecture overview
A monolithic architecture is decided for this project because the user base of 305 is small. This style fits the constraints of 5 doctors and 300 patients without requiring complex infrastructure. Main building blocks include the core web application, a PostgreSQL database, and a background job processor. The system relies on vertical scaling rather than horizontal distribution. No caching layer is needed since performance demands remain modest. The design prioritizes simplicity over distributed complexity for this scale.

## 2. Components and responsibilities
*   **Web API**: Serves REST endpoints for appointment booking and schedule management for patients and doctors.
*   **Database**: PostgreSQL stores appointment records, user details, and doctor availability data reliably.
*   **Job Processor**: Handles asynchronous tasks, including sending email and SMS reminders to users.
*   **External Integrations**: Manages connections with selected email and SMS service providers for notifications.

## 3. Data flow
A patient submits a booking request via the web interface. The application validates the data and writes the appointment to PostgreSQL. A job processor queries the database for upcoming appointments and triggers notifications via external providers. Doctors access their schedules by reading from the database through the API. Updates to availability are written directly to the primary data store.

## 4. API architecture
The system adopts a REST API, as decided, to align with the project’s scope. Primary operations support appointment creation, cancellation, and retrieval. Additional endpoints manage doctor schedule submissions and availability definitions. Interface exposure includes role-based access for patients and distinct administrative views for clinicians.

Error responses follow standard HTTP status codes with descriptive JSON messages. No versioning strategy is currently defined. Real-time capabilities remain unspecified, so WebSocket integration is deferred. This approach simplifies integration with external email and SMS providers. Client-side implementation remains general without specific framework constraints.

## 5. Database architecture and data model
PostgreSQL serves as the primary persistence layer, chosen for its relational integrity. Main entities include Patients, Doctors, Appointments, and Schedules. Appointments reference specific Doctors and Patients through foreign key constraints. Schedule entries track daily availability patterns for each of the five doctors.

Data volume is unspecified, so advanced partitioning is not yet required. Basic indexing on appointment dates and status fields supports efficient querying. No geospatial or media storage columns are defined, as these features remain unknown. The schema avoids denormalization to maintain data consistency. Current architecture supports the expected three hundred users without specialized optimization.

## 6. Authentication
The decision on the specific authentication method is not yet decided, as the requirements explicitly list authentication as an unknown. The system must support distinct sessions for patients and doctors. Since no protocol was selected, alternatives like token-based or session-based access remain open. This choice depends on unspecified details regarding how users will interact with the booking and scheduling interfaces.

## 7. Caching
No caching layer is needed for this application. The decision against caching was finalized, meaning the system will rely directly on the database for data retrieval. Given the moderate user base, direct database queries are sufficient for handling appointment bookings and schedule management without introducing additional infrastructure.

## 8. External services
The project depends on two external integrations:
*   An email service provider to transmit reservation confirmations and upcoming appointment alerts to registered patients.
*   An SMS service provider to deliver text message reminders, ensuring patients receive notifications even when email access is limited.

## 9. Security considerations
Key security risks include unauthorized access to medical schedules and interception of contact information:
*   Input validation must be enforced on all API endpoints to prevent malicious data injection.
*   Secrets for external service providers will be stored in environment variables rather than in code.
*   Role-based access control will strictly separate patient and doctor capabilities.
*   Specific regulatory requirements remain unclear, as security standards were not detailed in the initial requirements.

## 10. Scaling
The system is designed as a monolith, a decision settled for this specific user base of 305 patients and 5 doctors. Horizontal scaling is not needed, so no distributed infrastructure or load balancers are planned. As traffic fluctuates, the single application instance handles requests directly without sharding. Data volumes remain unspecified, but the PostgreSQL database chosen for storage is managed centrally rather than partitioned. No additional caching layers are included in the architecture because they are not deemed necessary for the current constraints. Future growth beyond these known limits would require revisiting the monolithic structure and scaling strategies.

## 11. Failure handling
When external email or SMS providers experience outages, background job processing manages the sending process. Specific retry mechanisms or timeout thresholds are not detailed in the current design data. The asynchronous processing layer decouples the application from these external dependencies, allowing the core booking functions to remain operational during temporary service disruptions. Internal component failures are handled by the standard error management of the monolithic architecture. Because the system is not designed for high availability or multi-region deployment, failover strategies rely on the underlying infrastructure provider rather than custom application logic.

## 12. Trade-offs and rationale
- A monolithic architecture was chosen over microservices to reduce complexity for a small user base.
- REST was selected as the API style, prioritizing simplicity over GraphQL’s flexibility.
- PostgreSQL was picked for relational data integrity, rather than a document-based store.
- No caching layer was included to avoid unnecessary infrastructure costs.
- Asynchronous processing is required to handle reminder emails and SMS without blocking requests.
- Horizontal scaling was rejected because the expected load is modest and fixed at 305 users.

## Rating (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 
