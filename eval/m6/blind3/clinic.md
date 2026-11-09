# Blind review round 2 (three arms): clinic

## Design X

## 1. Architecture overview
The system follows a monolith architecture to streamline development and reduce operational complexity. This style is appropriate for the 305 users in the expected scale, as horizontal scaling is not needed. A single deployable unit handles all business logic, providing a cohesive experience for both patients and doctors. Each developer works within the same codebase, simplifying refactoring. This design fits tightly with the central data storage assumption. There is no need for distributed architectures, which would add unnecessary overhead at this scale. The system is designed to grow vertically if required. Overall, this approach keeps the deployment model simple. It allows rapid production of the core features such as appointment booking and schedule management.

## 2. Components and responsibilities
*   **Web API layer**: This is a REST interface that handles all client requests. It manages authentication sessions for patients and doctors specifically.
*   **Application core**: The first part of the monolith handles business rules for online appointment booking. It coordinates the main service logic for patient and doctor views.
*   **Scheduler component**: This part of the moduli manages daily schedules for doctors. It ensures all appointment requests align with slot availability.
*   **Async messaging component**: This component handles the asynchronous reminders, specifically email and SMS notifications. It is responsible for sending the messages promptly.
*   **External integration service**: The monolith owns the clients for external email and SMS providers. It sends the requests for the notifications.
*   **Data access layer**: The monolith contains components for all database access. It writes appointment and user data to the primary store.

## 3. Data flow
A user logs in and sends a REST request to the monolith. The application verifies the patient or doctor role by checking the authentication token. The appointment booking or schedule management service queries the central database for existing records. The service then modifies the relevant data and writes the update to the store. If a reminder is required, the application posts a message to the internal queue. The asynchronous processor reads the message and triggers the integration service for email and SMS. The system then sends the reminders to the relevant external email provider.

## 4. API architecture
We use a REST API because it provides straightforward stateless interactions for the web front-end, avoiding unnecessary complexity for this user base. The primary operations focus on authentication, appointment creation, and schedule retrieval. Patients access endpoints to view available slots and book appointments, while doctors manage their daily schedules. Specific routes handle creation of appointments and cancellation workflows. 

For error handling, the system returns standard HTTP status codes with a consistent JSON body containing a machine-readable error code and a human-readable message. This ensures the client application can handle failures uniformly without parsing free-text responses. Resource versioning is unnecessary at this scale, so we rely on stable endpoint contracts. Data payloads remain simple JSON structures, optimizing for quick parsing and transmission over standard web connections.

## 5. Database architecture and data model
PostgreSQL serves as the primary database due to its strong relational integrity and ACID compliance, which are critical for accurate scheduling and financial-like transactional consistency. The data model centers on three main entities: Users, Doctors, and Appointments. Users store profile data for both patients and medical staff. The Doctors table extends this profile to include availability rules. 

Appointments link specific patients to doctors via foreign keys, recording the scheduled time, status, and type. A many-to-one relationship exists between appointments and both patients and doctors. We index columns on appointment dates and status to speed up the querying of daily schedules. Given the modest user count, partitioning is not required. The schema ensures that no two conflicting bookings can exist for the same doctor at the same time through unique constraints.

## 6. Authentication
The system uses JWT-based authentication for both patients and doctors, supporting standard email and password login. Since users access role-specific views, tokens embed role claims to enforce access control at the API layer. With 305 users and no specified compliance requirements, session lifetime is set to 8 hours with automatic refresh via short-lived refresh tokens. This approach fits the monolith architecture without requiring external identity providers.

## 7. Caching
Caching is not needed for this application. The user base of 305 and unspecified peak requests per second indicate minimal read load, making an in-memory cache layer unnecessary. PostgreSQL alone handles the required query performance for appointment lookups and schedule management.

## 8. External services
- Email provider: Delivers appointment confirmation messages and reminder notifications to patients via email.
- SMS provider: Sends time-sensitive appointment reminders to patients over short message service.

Both integrations are invoked by the asynchronous processing pipeline, ensuring reminder delivery does not block user-facing requests.

## 9. Security considerations
- Input validation is enforced at the API boundary using schema-based validation to prevent injection attacks.
- Secrets (provider API keys, database credentials) are stored outside the codebase in an environment-based secret store.
- Access control is enforced via JWT role claims; patient endpoints are invisible to doctors and vice versa.
- Passwords are hashed with bcrypt before storage in PostgreSQL.
- All external communication uses HTTPS to protect data in transit.

## 10. Scaling
The system operates within a single-node deployment footprint. Given the expected user base and traffic levels, the current architecture supports anticipated load without architectural change. Asynchronous processing ensures that notification tasks do not block user-facing request threads. Should data volumes grow significantly, the PostgreSQL instance can be scaled vertically. No partitioning or sharding strategies are required at this stage.

## 11. Failure handling
The system relies on PostgreSQL for data persistence. Connection timeouts are configured to prevent indefinite blocking during database unavailability. External email and SMS providers are wrapped in retry mechanisms to handle transient network errors. If notifications fail after retries, the system logs the failure for manual review. There is no automated fallback for communication channels.

## 12. Trade-offs and rationale
*   **Monolith over microservices:** Simpler deployment and lower operational overhead suit the small user base. Network latency between service boundaries is avoided.
*   **PostgreSQL over NoSQL:** Relational integrity is crucial for schedule logic and booking conflicts. Transactional guarantees prevent double-booking scenarios.
*   **REST over WebSockets:** Batch and simple request-response patterns suit appointment booking flows. Reduced connection management complexity aligns with the absence of realtime requirements.

## Rating: Design X (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 

## Design Y

## 1. Architecture overview
A modular monolith suits this project because the user base is small and functional boundaries are clear. This approach simplifies deployment and reduces operational overhead compared to microservices. The system consists of a single application server handling web traffic, a relational database for persistence, and a background worker for asynchronous message delivery. This structure ensures that appointment booking, schedule management, and reminder generation remain tightly coupled within one codebase while maintaining logical separation of concerns.

## 2. Components and responsibilities
- **API Gateway**: Manages incoming HTTP requests, handles authentication for Patients and Doctors, and routes traffic to appropriate service modules.
- **Booking Engine**: Owns the core logic for creating, updating, and canceling appointments while enforcing schedule constraints.
- **Schedule Manager**: Handles doctor daily schedule configuration, including available time slots and working hours management.
- **Notification Service**: Integrates with external SMS and email providers to dispatch appointment reminders and confirmations asynchronously.
- **User Management**: Maintains patient and doctor profiles, credential verification, and role-based access control permissions.

## 3. Data flow
A patient submits a booking request via the web interface. The API Gateway validates the request and forwards it to the Booking Engine. The engine checks availability against the Doctor’s schedule stored in the database. Upon successful creation, the appointment is persisted to the database. The system then enqueues a notification task. The Notification Service retrieves this task, formats the message, and transmits it via the configured SMS or email provider.

## 4. API architecture
The system uses a REST API because it favors simplicity and wide client compatibility for web-based interaction. JSON payloads ensure easy integration with both frontend and external services. Key operations include:

*   `POST /appointments`: Creates a new booking with patient, doctor, and time data.
*   `PUT /schedules`: Updates a doctor’s daily availability or time slots.
*   `GET /appointments`: Retrieves appointments filtered by user role or date.
*   `POST /notifications`: Triggers SMS or email reminder dispatch via providers.

Error handling follows standard HTTP status codes, with structured JSON error bodies for details. Versioning is omitted as the user base is small and schema stability is high.

## 5. Database architecture and data model
PostgreSQL serves as the primary database, offering strong relational integrity for scheduling logic. Main entities include `Patients`, `Doctors`, `Schedules`, and `Appointments`. Each `Appointment` references one `Patient` and one `Doctor`. `Schedules` are uniquely linked to specific `Doctors` and dates, defining available time slots. `Appointments` also reference specific `Schedule` slots to prevent double-booking.

Indexes are added on `Appointments` for `doctor_id` and `date` to speed up lookup queries. No partitioning is required given the expected scale of 300 users. Data volume remains modest, fitting comfortably within standard relational storage limits.

## 6. Authentication
Role-based authentication will distinguish Patients from Doctors using JWT tokens.  
Since both roles require secure account access, server-side sessions will store token validity for 24 hours.  
Authentication applies to all core features, ensuring only Patients can book appointments and only Doctors can manage schedules.  
This approach supports the approx. 300 patient scale without complex infrastructure.

## 7. Caching
Caching is not needed for this project.  
With approx. 300 patients and no specified peak requests per second, database queries will perform sufficiently without an additional caching layer.  
Appointment data changes frequently, making cache invalidation complex relative to the scale benefits.

## 8. External services
The system depends on an SMS provider to deliver appointment reminder messages to patients.  
It also integrates with an email service to send notification and confirmation messages.  
These external services handle the actual message delivery while the application manages scheduling and content generation.

## 9. Security considerations
- Input validation prevents malicious data entry when booking appointments or managing schedules.  
- Secrets handling ensures API credentials for SMS and email services are stored in environment variables, not code.  
- Access control enforces role separation, preventing Patients from modifying doctor schedules.  
- Passwords are hashed using bcrypt to protect user credentials during storage.

## 10. Scaling
The anticipated user base of approximately 300 patients supports a single-node deployment. No horizontal scaling is required for this scale. Stateful data persists in a centralized relational database while stateless web nodes can be replaced individually. This configuration minimizes infrastructure complexity and cost while easily accommodating the defined traffic limits.

## 11. Failure handling
The system isolates external messaging dependencies to prevent core booking failures. If SMS or email services fail, the application logs the error and displays a user confirmation without blocking the appointment creation process. Direct database connections rely on standard connection pooling with defined timeouts to prevent thread exhaustion during connectivity issues. Critical data operations remain synchronous, ensuring appointment integrity during partial service degradation.

## 12. Trade-offs and rationale
- **Database Selection**: Use a relational database for transactional integrity over NoSQL flexibility, prioritizing reliable schedule availability and appointment data consistency.
- **Deployment Model**: Select a single-node setup over multi-node clustering, reducing operational overhead since the specified user count does not justify distributed complexity.
- **Messaging Coupling**: Decouple notification services from booking logic to maintain core functionality when external providers experience uptime issues.

## Rating: Design Y (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 

## Design Z

## 1. Architecture overview
The project follows a monolithic architecture, as this approach fits the modest scale of 305 users and avoids unnecessary complexity. This single-service structure simplifies deployment and maintenance for a clinic management system. The main building blocks include a web application server, a PostgreSQL database, and a background worker system. These components work together to provide appointment scheduling, reminder notifications, and schedule management without splitting the system into separate microservices. This decision is confirmed by the project's requirements and scale constraints.

## 2. Components and responsibilities
*   **API Service**: This component handles RESTful endpoints for patient and doctor interactions. It manages all HTTP requests and validates incoming data for appointments and schedules.
*   **Database**: PostgreSQL stores all persistent data, including user profiles, appointment records, and doctor availability calendars. It serves as the single source of truth for the system.
*   **Background Worker**: This component processes non-blocking tasks, specifically sending email and SMS reminders. It pulls notification jobs from a queue to ensure timely delivery without delaying API responses.
*   **Notification Adapters**: These interfaces connect with external email and SMS services. They abstract the communication details from the core business logic.

## 3. Data flow
A user submits a booking request via the REST API. The API service validates the input and writes the new appointment record to PostgreSQL. Simultaneously, it enqueues a reminder job for the background worker. Later, the worker retrieves this job and calls the appropriate email or SMS service adapter. These external services send the actual notifications to the user. For schedule management, requests read existing data from PostgreSQL and update records directly, returning the modified state to the client.

## 4. API architecture
REST was chosen for its simplicity and standard structure, fitting the web application's needs. Key operations include creating and managing appointments, updating doctor schedules, and triggering patient reminders. Authenticated patients access their specific booking history, while doctors manage their available slots. Since specific authentication methods are not yet defined, secure access controls must be designed once those details are confirmed. Basic error handling will follow standard HTTP status codes. Versioning is currently low priority given the small user base, but may be added if external third-party integrations expand. The design prioritizes clarity over complex query optimizations, ensuring all endpoints remain straightforward and easy to maintain for the development team.

## 5. Database architecture and data model
PostgreSQL will store the core entities: Patients, Doctors, Appointments, and Schedules. Each Patient maintains a one-to-many relationship with Appointments, while Doctors also link one-to-many to both Appointments and Schedule entries. A single Appointment record connects one specific Patient to one specific Doctor, preserving the booking details. Given the expected scale of 305 users, basic indexing on timestamp and foreign key fields is sufficient for performance. Partitioning or sharding is not required due to the manageable data volume. The relational structure supports the necessary integrity checks for booking conflicts, although specific conflict resolution logic remains undecided. Data storage needs justify this choice over document-oriented alternatives for this specific use case.

## 6. Authentication
The authentication mechanism is listed as unspecified in the requirements data. However, the system assumptions confirm that users authenticate to access their specific data. Consequently, the design requires role-based access control to distinguish between patients and doctors, ensuring each user only views authorized records. The specific authentication method, such as email and password or single sign-on, is not yet decided.

## 7. Caching
Caching is not needed for this project. The design decision explicitly rejected the implementation of a dedicated caching layer, as the project’s scale does not mandate this performance optimization. With a managed user base of three hundred and five individuals and no specified high-throughput requirements, direct database queries against the primary store are deemed sufficient to handle expected load.

## 8. External services
The application relies on two primary external integrations. An email service is used to dispatch appointment confirmation and reminder messages to registered users. An SMS service is utilized to send text message notifications and reminders, providing a redundant communication channel for urgent scheduling updates.

## 9. Security considerations
*   Strict input validation is required on all API endpoints to prevent injection attacks, given the reliance on user-generated form data.
*   Secrets for external email and SMS services must be stored securely, avoiding exposure in the application codebase.
*   Role-based access control is essential to prevent patients from viewing other users' data and to restrict scheduling management privileges to authorized medical staff.

## 10. Scaling
The system is designed as a monolith, and horizontal scaling is not needed for the expected user base of 305. Peak request rates and data volume are unspecified, so current design estimates may shift as details emerge. No additional scaling architecture is planned at this stage. The focus remains on a single, stable application instance for simplicity and low operational overhead.

## 11. Failure handling
Dependencies such as email and SMS services are assumed to remain available. If they drop out, reminders would fail, but specific retry or timeout behavior is undefined. The exact conflict resolution logic for double-booking is also not yet decided, leaving race condition handling unclear. These gaps must be resolved before production deployment.

## 12. Trade-offs and rationale
-   Chose REST over GraphQL for standard integration simplicity.
-   Decided on a simple monolith rather than a modular monolith to match low-scale needs.
-   Determined that a caching layer is not needed, prioritizing direct database access.
-   Adopted asynchronous processing to handle reminders, despite the small user count.
-   Rejected horizontal scaling, accepting single-instance limitations for this scale.

## Rating: Design Z (1-5, 5 = best)

- specific: 
- correct: 
- useful: 
- clear: 
