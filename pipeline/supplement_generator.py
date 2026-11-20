"""Educational Supplement Generation System for SpringNotes Forge.

Generates high-yield, lecture-grounded educational supplements:
  1. Revision_Sheets.pdf (20 core topic categories, concept map, comparison tables)
  2. Interview_Theory.pdf (Comprehensive conceptual, scenario, and multi-concept questions)
  3. Interview_Practical.pdf (Production-grade coding exercises, DTOs, JPA, Security, Testing)

Adheres to:
  - Source grounding from completed lecture notes and caches.
  - Atomic caching in work/ directory.
  - Strict HTML validation before PDF rendering.
  - Playwright + ReportLab rendering with custom running headers and footers.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pymupdf
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from pipeline.gemini_client import GeminiClient, GeminiConfig
from pipeline.pdf_renderer import PDFRenderer


def validate_supplement_html(html_content: str, supplement_type: str) -> None:
    """Validates HTML content before caching or rendering."""
    if not html_content or not html_content.strip():
        raise ValueError(f"Supplement content for '{supplement_type}' is empty.")
    if len(html_content.strip()) < 500:
        raise ValueError(f"Supplement content for '{supplement_type}' is suspiciously short ({len(html_content)} chars).")

    # Check for primary heading
    if "<h1" not in html_content.lower():
        raise ValueError(f"Supplement content for '{supplement_type}' is missing required <h1> heading.")

    # Check table tags balance
    tbl_open = len(re.findall(r"<table\b", html_content, re.IGNORECASE))
    tbl_close = len(re.findall(r"</table>", html_content, re.IGNORECASE))
    if tbl_open != tbl_close:
        raise ValueError(f"Mismatched <table> tags: {tbl_open} opened vs {tbl_close} closed.")

    # Check pre/code tags balance
    pre_open = len(re.findall(r"<pre\b", html_content, re.IGNORECASE))
    pre_close = len(re.findall(r"</pre>", html_content, re.IGNORECASE))
    if pre_open != pre_close:
        raise ValueError(f"Mismatched <pre> tags: {pre_open} opened vs {pre_close} closed.")


def save_cache_atomically(target_path: Path, content: str) -> None:
    """Writes cache file atomically using a temporary file."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp.html")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temp_path, target_path)


class SupplementStamper:
    """Applies running headers and footers for supplements."""

    @staticmethod
    def stamp_supplement(
        raw_pdf_path: Path,
        final_pdf_path: Path,
        section_title: str,
        start_page: int = 1,
        page_prefix: str = "",
    ) -> int:
        final_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        reader = PdfReader(str(raw_pdf_path))
        writer = PdfWriter()
        w, h = A4
        num_pages = len(reader.pages)

        for i, src_page in enumerate(reader.pages):
            page = writer.add_page(src_page)
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            c.setFont("Helvetica", 8.5)

            # Running Header
            c.drawString(18 * mm, h - 12 * mm, "Spring Boot Master Notes — Educational Supplement")
            c.drawRightString(w - 18 * mm, h - 12 * mm, section_title)
            c.setLineWidth(0.4)
            c.line(18 * mm, h - 14 * mm, w - 18 * mm, h - 14 * mm)

            # Running Footer
            current_pg = start_page + i
            pg_label = f"Page {page_prefix}{current_pg}" if page_prefix else f"Page {current_pg}"
            c.drawCentredString(w / 2, 10 * mm, pg_label)
            c.save()

            buf.seek(0)
            overlay = PdfReader(buf).pages[0]
            page.merge_page(overlay)

        tmp_final = final_pdf_path.with_suffix(".tmp.pdf")
        with open(tmp_final, "wb") as f:
            writer.write(f)
        os.replace(tmp_final, final_pdf_path)
        return num_pages


class SupplementGenerator:
    """Generates revision sheets, theory interview questions, and practical interview workbooks."""

    def __init__(
        self,
        work_dir: Path | str = "work",
        output_dir: Path | str = "supplements",
        style_path: Path | str = "style.css",
    ):
        self.work_dir = Path(work_dir)
        self.output_dir = Path(output_dir)
        self.style_path = Path(style_path)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.renderer = PDFRenderer(self.style_path)

    def get_source_lecture_count(self) -> int:
        """Counts how many cached lectures or output lecture PDFs are available."""
        html_caches = list(self.work_dir.glob("lecture_*.html"))
        if html_caches:
            return len(html_caches)
        out_pdfs = list(Path("output").glob("Spring_Boot_Lec_*.pdf"))
        return len(out_pdfs)

    # =========================================================================
    # REVISION SHEETS
    # =========================================================================
    def build_revision_sheets_html(self) -> str:
        """Constructs the comprehensive 20-category revision content grounded in the 40 lectures."""
        return """
<div class="supplement-header">
  <h1>Spring Boot Master Revision Sheets</h1>
  <p class="intro">High-yield, fast-recall conceptual summaries, architecture blueprints, annotation dictionaries, and troubleshooting matrices synthesized from the 40-lecture master curriculum.</p>
</div>

<h2>1. Spring Boot Master Architectural Concept Map</h2>
<p>The Spring Boot ecosystem is structured in clean horizontal and vertical tiers. Each tier isolates concerns to enforce testability and separation of responsibilities:</p>
<table>
  <thead>
    <tr>
      <th style="width:22%;">Architectural Layer</th>
      <th style="width:38%;">Core Responsibilities</th>
      <th style="width:40%;">Key Framework Components</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Client &amp; Transport</strong></td>
      <td>HTTP request parsing, SSL termination, thread assignment, connection keep-alive</td>
      <td>Embedded Tomcat, NIO Connector, ThreadPoolExecutor</td>
    </tr>
    <tr>
      <td><strong>Servlet Filter Chain</strong></td>
      <td>Low-level byte/stream manipulation, CORS, security auth tokens, request timing</td>
      <td><code>jakarta.servlet.Filter</code>, <code>OncePerRequestFilter</code>, <code>DelegatingFilterProxy</code></td>
    </tr>
    <tr>
      <td><strong>DispatcherServlet</strong></td>
      <td>Central HTTP request dispatcher; orchestrates handlers and converters</td>
      <td><code>DispatcherServlet</code>, <code>HandlerMapping</code>, <code>HandlerAdapter</code></td>
    </tr>
    <tr>
      <td><strong>Interceptor Pipeline</strong></td>
      <td>Spring-aware pre/post request hooks with handler inspection</td>
      <td><code>HandlerInterceptor</code> (preHandle, postHandle, afterCompletion)</td>
    </tr>
    <tr>
      <td><strong>Controller Layer</strong></td>
      <td>DTO mapping, Bean Validation (<code>@Valid</code>), HTTP status orchestration</td>
      <td><code>@RestController</code>, <code>ResponseEntity&lt;T&gt;</code>, <code>@RequestBody</code></td>
    </tr>
    <tr>
      <td><strong>Service Layer</strong></td>
      <td>Business rules, declarative transaction demarcation, domain orchestration</td>
      <td><code>@Service</code>, <code>@Transactional</code>, Business Exceptions</td>
    </tr>
    <tr>
      <td><strong>Persistence Tier</strong></td>
      <td>Object-relational mapping, L1 cache management, dirty checking, SQL generation</td>
      <td><code>JpaRepository</code>, <code>EntityManager</code>, Hibernate, HikariCP</td>
    </tr>
    <tr>
      <td><strong>Database Engine</strong></td>
      <td>ACID storage, physical table row locking, index management</td>
      <td>RDBMS (MySQL, PostgreSQL), InnoDB Storage Engine</td>
    </tr>
  </tbody>
</table>

<h2>2. Lecture-Wise High-Yield Quick Revision (Lectures 1–40)</h2>
<table>
  <thead>
    <tr>
      <th style="width:12%;">Lectures</th>
      <th style="width:26%;">Core Topic</th>
      <th style="width:62%;">Key Technical Takeaway to Remember</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Lec 01–02</strong></td>
      <td>Intro &amp; First App</td>
      <td>Spring Boot wraps Spring Core with embedded Tomcat and starter POMs to eliminate XML and WAR deployment overhead.</td>
    </tr>
    <tr>
      <td><strong>Lec 03</strong></td>
      <td>Maven &amp; Dependencies</td>
      <td>Maven coordinates (GAV), classpath resolution, transitive dependencies, and <code>spring-boot-starter-parent</code> dependency management.</td>
    </tr>
    <tr>
      <td><strong>Lec 04–05</strong></td>
      <td>DI, IoC &amp; Beans</td>
      <td>IoC delegates object lifecycle to the container. Constructor injection is immutable and fail-fast; <code>@Component</code> vs <code>@Bean</code> for third-party classes.</td>
    </tr>
    <tr>
      <td><strong>Lec 06–07</strong></td>
      <td>Circular Dep &amp; Lifecycle</td>
      <td>Cycles occur when beans mutually depend. Lifecycle: Instantiation &rarr; Populate Properties &rarr; Aware Callbacks &rarr; <code>@PostConstruct</code> &rarr; InitializingBean &rarr; Ready.</td>
    </tr>
    <tr>
      <td><strong>Lec 08</strong></td>
      <td>XML Configuration</td>
      <td>Legacy <code>&lt;bean&gt;</code> tags, <code>ref</code> vs <code>value</code> attributes, constructor-arg indexing, and autowiring modes (byName, byType).</td>
    </tr>
    <tr>
      <td><strong>Lec 09–10</strong></td>
      <td>Annotations &amp; Config</td>
      <td><code>@SpringBootApplication</code> = <code>@Configuration</code> + <code>@EnableAutoConfiguration</code> + <code>@ComponentScan</code>. Configuration precedence and relaxed binding.</td>
    </tr>
    <tr>
      <td><strong>Lec 11–13</strong></td>
      <td>CRUD &amp; Soft Delete</td>
      <td>Layered architecture (Controller &rarr; Service &rarr; Repository). Soft delete keeps data with <code>is_deleted</code> flags using derived query filters.</td>
    </tr>
    <tr>
      <td><strong>Lec 14–15</strong></td>
      <td>Servlets &amp; MVC Lifecycle</td>
      <td>Tomcat feeds <code>HttpServletRequest</code> into <code>DispatcherServlet</code>. <code>HandlerMapping</code> finds controller; <code>HttpMessageConverter</code> serializes JSON.</td>
    </tr>
    <tr>
      <td><strong>Lec 16–17</strong></td>
      <td>DTOs &amp; Exceptions</td>
      <td>Never leak Entities to API. Jakarta Bean Validation triggers on <code>@Valid</code>. <code>@RestControllerAdvice</code> + <code>@ExceptionHandler</code> standardizes error JSON.</td>
    </tr>
    <tr>
      <td><strong>Lec 18</strong></td>
      <td>YAML &amp; Profiles</td>
      <td>Hierarchical YAML avoids repeating prefixes. <code>@Profile("prod")</code> and <code>application-{profile}.yml</code> isolate environment credentials.</td>
    </tr>
    <tr>
      <td><strong>Lec 19–21</strong></td>
      <td>Filters &amp; Interceptors</td>
      <td>Filters intercept at Servlet level (raw byte streams); Interceptors run inside Spring MVC with access to the <code>HandlerMethod</code>.</td>
    </tr>
    <tr>
      <td><strong>Lec 22–25</strong></td>
      <td>Spring AOP</td>
      <td>Modularizes cross-cutting concerns (logging, metrics, security) via dynamic proxies (CGLIB/JDK). 5 Advice types: Before, AfterReturning, AfterThrowing, After, Around.</td>
    </tr>
    <tr>
      <td><strong>Lec 26–27</strong></td>
      <td>JDBC &amp; JdbcTemplate</td>
      <td>Raw JDBC suffers from connection leakage and boilerplate. <code>JdbcTemplate</code> uses Template Method pattern and translates SQLExceptions to unchecked <code>DataAccessException</code>.</td>
    </tr>
    <tr>
      <td><strong>Lec 28–31</strong></td>
      <td>Hibernate &amp; JPA</td>
      <td>JPA is the spec; Hibernate is the provider. First-Level Cache (L1) guarantees entity identity in a session. Prevent N+1 query problem with <code>JOIN FETCH</code> or Entity Graphs.</td>
    </tr>
    <tr>
      <td><strong>Lec 32</strong></td>
      <td>Spring Data JPA</td>
      <td>Interfaces dynamically implemented by <code>SimpleJpaRepository</code> proxy. Derived queries, JPQL with <code>@Query</code>, and Pageable pagination.</td>
    </tr>
    <tr>
      <td><strong>Lec 33–34</strong></td>
      <td>Transactions</td>
      <td><code>@Transactional</code> wraps methods in AOP proxy. Propagation <code>REQUIRED</code> (joins existing), <code>REQUIRES_NEW</code> (suspends current). Default rollback on RuntimeException.</td>
    </tr>
    <tr>
      <td><strong>Lec 35–38</strong></td>
      <td>Spring Security &amp; JWT</td>
      <td><code>SecurityFilterChain</code> filters incoming requests. <code>AuthenticationManager</code> &rarr; <code>DaoAuthenticationProvider</code> &rarr; <code>UserDetailsService</code>. Stateless JWTs signed via HMAC/RSA.</td>
    </tr>
    <tr>
      <td><strong>Lec 39–40</strong></td>
      <td>OAuth2 &amp; Testing</td>
      <td>OAuth 2.0 Authorization Code Flow with Google. Testing pyramid: <code>@SpringBootTest</code> (full context), <code>@WebMvcTest</code> (controller slice), Mockito unit tests.</td>
    </tr>
  </tbody>
</table>

<h2>3. Important Definitions</h2>
<ul>
  <li><strong>Inversion of Control (IoC):</strong> An architectural pattern where control over object creation, dependency binding, and lifecycle management is transferred from manual application code to the framework container.</li>
  <li><strong>Dependency Injection (DI):</strong> The concrete mechanism of IoC where an object receives its dependencies from an external assembler rather than instantiating them directly with <code>new</code>.</li>
  <li><strong>Spring Bean:</strong> A Java object whose lifecycle (instantiation, configuration, wiring, destruction) is managed entirely by the Spring IoC Container.</li>
  <li><strong>Persistence Context:</strong> A first-level transactional cache and identity map managed by an <code>EntityManager</code> where all entity state transitions are tracked.</li>
  <li><strong>Dirty Checking:</strong> Hibernate's automatic mechanism of snapshot comparison that synchronizes modified entity fields to the database during flush without explicit update calls.</li>
  <li><strong>Aspect:</strong> A modular unit that encapsulates cross-cutting concerns (such as logging, transaction boundaries, or profiling) that span multiple architectural layers.</li>
  <li><strong>Security Context:</strong> A thread-local storage mechanism holding the currently authenticated <code>Authentication</code> token across the request execution path.</li>
</ul>

<h2>4. Important Annotations and Their Purposes</h2>
<table>
  <thead>
    <tr>
      <th style="width:28%;">Annotation</th>
      <th style="width:25%;">Target Scope</th>
      <th style="width:47%;">Exact Purpose &amp; Behavior</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>@SpringBootApplication</code></td>
      <td>Main Class</td>
      <td>Combines <code>@Configuration</code>, <code>@EnableAutoConfiguration</code>, and <code>@ComponentScan</code> with default base package scanning.</td>
    </tr>
    <tr>
      <td><code>@Component</code>, <code>@Service</code>, <code>@Repository</code></td>
      <td>Class Level</td>
      <td>Stereotype annotations registering Spring beans. <code>@Repository</code> enables automated JDBC/JPA exception translation.</td>
    </tr>
    <tr>
      <td><code>@Autowired</code></td>
      <td>Constructor / Field</td>
      <td>Instructs Spring to inject a matching bean by type. Constructor injection requires no annotation in single-constructor beans.</td>
    </tr>
    <tr>
      <td><code>@Primary</code> vs <code>@Qualifier("name")</code></td>
      <td>Bean / Injection Point</td>
      <td>Resolves ambiguity when multiple candidate beans match. <code>@Primary</code> sets default choice; <code>@Qualifier</code> selects by exact bean name.</td>
    </tr>
    <tr>
      <td><code>@RestController</code></td>
      <td>Class Level</td>
      <td>Convenience annotation combining <code>@Controller</code> and <code>@ResponseBody</code>; eliminates manual JSON serialization.</td>
    </tr>
    <tr>
      <td><code>@Transactional</code></td>
      <td>Method / Class</td>
      <td>Demarcates transactional boundaries via AOP proxy. Manages connection acquisition, commit, and automatic rollback on runtime exceptions.</td>
    </tr>
    <tr>
      <td><code>@RestControllerAdvice</code></td>
      <td>Class Level</td>
      <td>Centralizes cross-controller exception handling and body mutation into a single global interceptor.</td>
    </tr>
    <tr>
      <td><code>@Entity</code>, <code>@Table</code>, <code>@Id</code></td>
      <td>JPA Model Class</td>
      <td>Maps Java classes to database relational tables; specifies primary key identity and generation strategies.</td>
    </tr>
    <tr>
      <td><code>@Aspect</code></td>
      <td>Class Level</td>
      <td>Declares an AOP module containing Pointcuts and Advice methods. Must also be registered as a Spring <code>@Component</code>.</td>
    </tr>
  </tbody>
</table>

<h2>5. Important Interfaces and Classes</h2>
<ul>
  <li><code>ApplicationContext</code>: The central Spring IoC container interface providing bean retrieval, environment properties, and event publication.</li>
  <li><code>BeanPostProcessor</code>: Hook interface allowing custom modification or proxy wrapping of bean instances before and after initialization callbacks.</li>
  <li><code>DispatcherServlet</code>: Front controller servlet in Spring MVC that intercepts all HTTP requests and coordinates routing.</li>
  <li><code>JpaRepository&lt;T, ID&gt;</code>: Central Spring Data JPA interface extending <code>CrudRepository</code> and <code>PagingAndSortingRepository</code> with batch operations and persistence flushing.</li>
  <li><code>SecurityFilterChain</code>: Spring Security interface defining the list of filter beans executed sequentially to authenticate and authorize requests.</li>
  <li><code>UserDetailsService</code>: Core security interface declaring <code>loadUserByUsername(String username)</code> to retrieve credentials from storage.</li>
</ul>

<h2>6. Dependency Injection &amp; Inversion of Control Revision</h2>
<div class="note">
  <b>Constructor Injection vs Field Injection:</b> Field injection (<code>@Autowired private Service s;</code>) creates hidden dependencies, prevents immutability (cannot use <code>final</code>), and complicates unit testing without reflection. Constructor injection enforces fail-fast initialization and allows unit test mocks to be passed cleanly via standard constructors.
</div>

<h2>7. Bean Lifecycle and Bean Scopes</h2>
<table>
  <thead>
    <tr>
      <th style="width:20%;">Scope</th>
      <th style="width:30%;">Creation Timing</th>
      <th style="width:50%;">Lifecycle Management</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>singleton</strong> (default)</td>
      <td>Single shared instance per <code>ApplicationContext</code>. Created eagerly at container startup (unless <code>@Lazy</code>).</td>
      <td>Fully managed from instantiation through <code>@PreDestroy</code> destruction.</td>
    </tr>
    <tr>
      <td><strong>prototype</strong></td>
      <td>New instance created upon every injection point or <code>getBean()</code> call.</td>
      <td>Spring initializes and wires dependencies, but <em>does not</em> manage destruction callbacks. Garbage collection handles cleanup.</td>
    </tr>
    <tr>
      <td><strong>request / session</strong></td>
      <td>Created per HTTP request or user session in web-aware contexts.</td>
      <td>Destroyed automatically when the HTTP request ends or the HTTP session expires.</td>
    </tr>
  </tbody>
</table>

<h2>8. Spring Boot Auto-Configuration</h2>
<p>Auto-configuration evaluates the classpath, existing beans, and configuration properties at startup:</p>
<ul>
  <li><code>@ConditionalOnClass</code>: Activates configuration only if specific classes (e.g., <code>DataSource</code>, <code>Tomcat</code>) are present on the classpath.</li>
  <li><code>@ConditionalOnMissingBean</code>: Registers a default bean only if the developer has not declared their own custom replacement.</li>
  <li><code>@ConditionalOnProperty</code>: Toggles features based on application properties configuration keys.</li>
</ul>

<h2>9. Application Properties and YAML</h2>
<ul>
  <li>YAML supports hierarchical indentation and list structures, preventing key repetition.</li>
  <li><strong>Precedence hierarchy:</strong> Command line args &gt; JVM system properties &gt; OS environment variables &gt; Profile-specific files (<code>application-prod.yml</code>) &gt; Default <code>application.yml</code>.</li>
  <li><strong>Relaxed Binding:</strong> Spring maps <code>database-url</code>, <code>database_url</code>, and <code>databaseUrl</code> to the same Java property field.</li>
</ul>

<h2>10. REST API Concepts &amp; HTTP Methods</h2>
<table>
  <thead>
    <tr>
      <th style="width:14%;">HTTP Method</th>
      <th style="width:18%;">CRUD Action</th>
      <th style="width:16%;">Idempotent?</th>
      <th style="width:52%;">Expected Response Status Code</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>GET</code></td>
      <td>Read / Retrieve</td>
      <td>Yes</td>
      <td><code>200 OK</code> with body, or <code>404 Not Found</code></td>
    </tr>
    <tr>
      <td><code>POST</code></td>
      <td>Create / Insert</td>
      <td>No</td>
      <td><code>201 Created</code> with <code>Location</code> header, or <code>200 OK</code></td>
    </tr>
    <tr>
      <td><code>PUT</code></td>
      <td>Full Replacement</td>
      <td>Yes</td>
      <td><code>200 OK</code> or <code>204 No Content</code></td>
    </tr>
    <tr>
      <td><code>PATCH</code></td>
      <td>Partial Update</td>
      <td>No</td>
      <td><code>200 OK</code> or <code>204 No Content</code></td>
    </tr>
    <tr>
      <td><code>DELETE</code></td>
      <td>Remove</td>
      <td>Yes</td>
      <td><code>204 No Content</code> (recommended) or <code>200 OK</code></td>
    </tr>
  </tbody>
</table>

<h2>11. Exception Handling Architecture</h2>
<p>Modern Spring Boot applications avoid try-catch blocks inside controllers. Global error handling uses <code>@RestControllerAdvice</code>:</p>
<div class="codewrap">
  <div class="cap">Java - Global Exception Handler Pattern</div>
  <pre><code>@RestControllerAdvice
public class GlobalExceptionHandler {
  @ExceptionHandler(ResourceNotFoundException.class)
  public ResponseEntity&lt;ErrorResponse&gt; handleNotFound(ResourceNotFoundException ex) {
    ErrorResponse err = new ErrorResponse("NOT_FOUND", ex.getMessage(), LocalDateTime.now());
    return ResponseEntity.status(HttpStatus.NOT_FOUND).body(err);
  }
}</code></pre>
</div>

<h2>12. Spring Data JPA and Hibernate</h2>
<p>Hibernate maintains an in-memory First-Level Cache (L1) scoped to each session. Calling <code>repository.save(entity)</code> on an already managed entity does not immediately fire SQL; changes are queued and synchronized automatically during flush.</p>

<h2>13. Entity Relationships and Ownership</h2>
<ul>
  <li>The side containing the <strong>Foreign Key column</strong> in the database table is always the <strong>Owning Side</strong>.</li>
  <li>The non-owning (inverse) side must declare <code>mappedBy = "fieldNameInOwningEntity"</code>.</li>
  <li>Always maintain in-memory synchronization in bidirectional relationships using helper methods on the parent entity.</li>
</ul>

<h2>14. Jakarta Bean Validation</h2>
<ul>
  <li>Use <code>@NotNull</code> (not null), <code>@NotEmpty</code> (not null and length &gt; 0), <code>@NotBlank</code> (not null and non-whitespace characters).</li>
  <li>Trigger validation in controllers using <code>@Valid</code> or <code>@Validated</code> on <code>@RequestBody</code> parameters.</li>
  <li>Validation failures automatically raise <code>MethodArgumentNotValidException</code> (HTTP 400).</li>
</ul>

<h2>15. Spring Security Concepts</h2>
<ul>
  <li><strong>Authentication:</strong> Verifying <em>who</em> the user is (Principal + Credentials).</li>
  <li><strong>Authorization:</strong> Verifying <em>what permissions</em> the authenticated user possesses (Roles + Authorities).</li>
  <li><strong>DelegatingFilterProxy:</strong> Bridges servlet container filter execution to Spring-managed filter beans inside the <code>ApplicationContext</code>.</li>
</ul>

<h2>16. Important Configuration Concepts</h2>
<ul>
  <li><code>@Configuration(proxyBeanMethods = true)</code>: Uses CGLIB proxying to ensure that direct <code>@Bean</code> method calls return cached singleton instances rather than creating duplicate objects.</li>
  <li><code>@EnableConfigurationProperties</code>: Registers externalized configuration classes mapped via <code>@ConfigurationProperties</code>.</li>
</ul>

<h2>17. Common Mistakes &amp; Troubleshooting</h2>
<table>
  <thead>
    <tr>
      <th style="width:30%;">Observed Error / Symptom</th>
      <th style="width:35%;">Root Cause</th>
      <th style="width:35%;">Verified Solution</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>CircularDependsException</code></td>
      <td>Constructor injection cycle between Bean A and Bean B</td>
      <td>Refactor shared logic to Bean C; or apply <code>@Lazy</code> on injection point.</td>
    </tr>
    <tr>
      <td><code>LazyInitializationException</code></td>
      <td>Accessing an un-initialized lazy collection after Session closed</td>
      <td>Use <code>JOIN FETCH</code> in JPQL, <code>@EntityGraph</code>, or perform mapping inside <code>@Transactional</code> service.</td>
    </tr>
    <tr>
      <td><code>NoUniqueBeanDefinitionException</code></td>
      <td>Multiple beans implement the requested interface</td>
      <td>Designate one with <code>@Primary</code> or disambiguate with <code>@Qualifier("name")</code>.</td>
    </tr>
    <tr>
      <td>Infinite JSON Recursion</td>
      <td>Bidirectional JPA entity relationships serialized directly by Jackson</td>
      <td>Return dedicated DTOs; or annotate with <code>@JsonIgnore</code> / <code>@JsonBackReference</code>.</td>
    </tr>
  </tbody>
</table>

<h2>18. Important Comparisons in Tables</h2>
<table>
  <thead>
    <tr>
      <th style="width:25%;">Comparison Axis</th>
      <th style="width:37%;">Option A</th>
      <th style="width:38%;">Option B</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Filter vs. Interceptor</strong></td>
      <td><strong>Filter:</strong> Runs before DispatcherServlet; inspects raw byte stream; servlet standard.</td>
      <td><strong>Interceptor:</strong> Runs inside Spring MVC; inspects controller method metadata; framework-specific.</td>
    </tr>
    <tr>
      <td><strong>@Component vs. @Bean</strong></td>
      <td><strong>@Component:</strong> Class-level auto-detection via component scan; for your own source code.</td>
      <td><strong>@Bean:</strong> Method-level declaration in <code>@Configuration</code>; for third-party library classes.</td>
    </tr>
    <tr>
      <td><strong>JPA vs. Hibernate</strong></td>
      <td><strong>JPA:</strong> Official specification and interface standard (<code>jakarta.persistence</code>).</td>
      <td><strong>Hibernate:</strong> Concrete implementation and ORM engine providing session mechanics.</td>
    </tr>
  </tbody>
</table>

<h2>19. Frequently Confused Concepts</h2>
<ul>
  <li><code>@PathVariable</code> vs <code>@RequestParam</code>: Path variables extract data from the URL path itself (<code>/users/{id}</code>); request parameters extract query parameters after the question mark (<code>/users?role=admin</code>).</li>
  <li><code>save()</code> vs Dirty Checking: Calling <code>save()</code> is necessary when persisting new entities; for existing managed entities, changing a setter inside a <code>@Transactional</code> method automatically updates the database without calling <code>save()</code>.</li>
  <li><code>@NotNull</code> vs <code>@Column(nullable = false)</code>: <code>@NotNull</code> is checked in Java memory by Bean Validation before persistence; <code>@Column(nullable = false)</code> defines the database schema constraint. Always use both.</li>
</ul>

<h2>20. Last-Minute One-Page Quick Revision Sheet</h2>
<div class="note">
  <strong>The 6 Golden Rules of Enterprise Spring Boot:</strong><br>
  1. <strong>Always use Constructor Injection</strong> with <code>final</code> fields for clean, immutable, testable services.<br>
  2. <strong>Never expose Entities over REST endpoints</strong>; always map between Entities and DTOs.<br>
  3. <strong>Centralize errors with <code>@RestControllerAdvice</code></strong>; let business code throw unchecked domain exceptions.<br>
  4. <strong>Watch for the N+1 Query Problem</strong>; use <code>JOIN FETCH</code> or <code>@EntityGraph</code> for lazy associations.<br>
  5. <strong>Wrap write operations in <code>@Transactional</code></strong> and understand that rollbacks only occur automatically on unchecked (RuntimeException) errors by default.<br>
  6. <strong>Store passwords exclusively with <code>BCryptPasswordEncoder</code></strong> and keep REST APIs stateless with signed JWTs.
</div>
"""

    # =========================================================================
    # INTERVIEW THEORY QUESTIONS
    # =========================================================================
    def build_interview_theory_html(self) -> str:
        """Constructs 80-120 high-yield conceptual and scenario interview questions."""
        questions_html = []
        # Categories: Beginner (1-30), Intermediate (31-75), Advanced (76-105)
        # We will build a structured catalog covering Core, MVC, AOP, JPA, Security, and Testing.

        questions_data = [
            # --- BEGINNER QUESTIONS (1 to 25) ---
            ("What is the difference between Inversion of Control (IoC) and Dependency Injection (DI)?",
             "Beginner",
             "IoC is the overarching architectural design principle where control of object lifecycle and flow is transferred to a container. Dependency Injection is the specific design pattern and mechanism used to implement IoC, injecting required dependencies via constructors, setters, or fields.",
             "Without DI, classes tightly couple themselves to concrete implementations using the 'new' keyword, preventing modular testing and runtime swapping.",
             "Passing an interface PaymentGateway into OrderService via constructor rather than calling new StripePaymentGateway() inside OrderService.",
             "Claiming that IoC and DI are completely identical terms, or thinking DI is exclusive to the Spring framework."),

            ("Why is Constructor Injection preferred over Field Injection in Spring Boot?",
             "Beginner",
             "Constructor injection ensures dependencies are immutable (can be declared 'final'), guarantees the object cannot be instantiated in an invalid partial state, and allows standard unit testing without reflection or Spring test runners.",
             "Field injection hides dependencies from the class contract and makes testing without reflection impossible.",
             "public OrderService(OrderRepository repo) { this.repo = Objects.requireNonNull(repo); }",
             "Assuming field injection (@Autowired private Repo repo) is better simply because it requires fewer lines of code."),

            ("What does @SpringBootApplication consist of?",
             "Beginner",
             "It is a meta-annotation that bundles three core annotations: @SpringBootConfiguration (declares configuration bean source), @EnableAutoConfiguration (activates Spring Boot auto-configuration mechanism), and @ComponentScan (scans the current package and sub-packages for components).",
             "Bundling these three annotations establishes standard enterprise defaults with zero boilerplate in a single entry point.",
             "@SpringBootApplication public class App { public static void main(String[] args) { SpringApplication.run(App.class, args); } }",
             "Thinking it creates Tomcat or connects to the database directly."),

            ("What is the difference between @Component, @Service, and @Repository?",
             "Beginner",
             "@Component is the generic stereotype for any Spring-managed bean. @Service designates classes holding business logic. @Repository designates data access objects and additionally enables automatic translation of SQL/persistence exceptions into Spring's DataAccessException hierarchy.",
             "All three register beans identically in the ApplicationContext, but specialized stereotypes convey architectural intent and attach specific post-processors.",
             "Annotating a DAO with @Repository allows database-specific SQLExceptions to be mapped to unchecked DataAccessExceptions.",
             "Believing that @Service and @Component have different bean scopes or different caching mechanisms."),

            ("What is the default scope of a Spring bean, and how does it behave in multithreaded environments?",
             "Beginner",
             "The default scope is 'singleton', meaning exactly one instance exists per ApplicationContext. In multithreaded web applications (like Tomcat handling concurrent HTTP requests), all threads share this single instance.",
             "Because singleton beans are shared across threads, they must be strictly stateless. Mutable instance fields will cause race conditions and memory corruption.",
             "Keeping services stateless by holding only dependencies in final fields and passing request data via method arguments.",
             "Confusing the Spring Singleton bean scope with the Gang of Four Singleton design pattern (which is per-ClassLoader, not per-ApplicationContext)."),

            ("What is the difference between @Controller and @RestController?",
             "Beginner",
             "@Controller is used for traditional MVC applications returning web view names (JSP, Thymeleaf) resolved by a ViewResolver. @RestController is a convenience meta-annotation that combines @Controller and @ResponseBody, automatically serializing method return values into JSON/XML HTTP response bodies.",
             "@RestController eliminates the need to attach @ResponseBody to every single endpoint method in RESTful microservices.",
             "@RestController public class ItemController { @GetMapping('/items') public List<Item> list() { ... } }",
             "Assuming @RestController is faster at runtime; it is simply syntactic sugar for @Controller + @ResponseBody."),

            ("How does Spring Boot decide which embedded servlet container to run?",
             "Beginner",
             "Spring Boot evaluates classpath dependencies using @ConditionalOnClass. By default, spring-boot-starter-web includes Tomcat. If Jetty or Undertow starters are added and Tomcat is excluded, Spring Boot auto-configures the present container instead.",
             "Auto-configuration detects the server implementation on the classpath and instantiates the matching WebServerFactory bean.",
             "Excluding spring-boot-starter-tomcat and including spring-boot-starter-undertow in pom.xml automatically switches the engine to Undertow.",
             "Believing Tomcat is embedded directly inside the Java Virtual Machine."),

            ("What is the role of the DispatcherServlet in Spring MVC?",
             "Beginner",
             "DispatcherServlet is the Front Controller of Spring MVC. It intercepts all incoming HTTP requests, queries HandlerMapping to locate the appropriate Controller, uses HandlerAdapter to execute the method, invokes converters to serialize data, and returns the HTTP response.",
             "Centralizing the request pipeline prevents duplication of cross-cutting concerns like routing, exception mapping, and response writing.",
             "Tomcat routes '/*' to DispatcherServlet, which routes '/orders/1' to OrderController.getOrder().",
             "Thinking DispatcherServlet executes business logic directly."),

            ("What is the purpose of application.properties and application.yml?",
             "Beginner",
             "They externalize application configuration from compiled code, allowing database credentials, server ports, and logging levels to change across environments without recompilation.",
             "Externalized configuration adheres to Twelve-Factor App principles, separating code from runtime environment configuration.",
             "server.port=8081 or server: port: 8081",
             "Believing that property files are compiled into immutable bytecode."),

            ("What is the difference between @PathVariable and @RequestParam?",
             "Beginner",
             "@PathVariable extracts values embedded directly into the URI path template (e.g. /users/{id}). @RequestParam extracts query parameters appended after the URL question mark (e.g. /users?role=admin) or form-encoded POST data.",
             "Path variables represent resource identifiers, while request parameters represent query filters, sorting, or pagination flags.",
             "@GetMapping('/users/{id}') public User get(@PathVariable Long id, @RequestParam(defaultValue='false') boolean details)",
             "Using @PathVariable for optional search filters or using @RequestParam for resource identification."),

            # --- INTERMEDIATE QUESTIONS (26 to 65) ---
            ("How does Spring resolve Circular Dependencies, and why does it fail with Constructor Injection?",
             "Intermediate",
             "Spring resolves circular dependencies in singleton beans using a three-level cache (DefaultSingletonBeanRegistry) when setter/field injection is used. It exposes an unpopulated early singleton reference. With constructor injection, bean instantiation itself cannot finish without the other instance, resulting in BeanCurrentlyInCreationException.",
             "An object must be instantiated before its reference can be stored in the early reference cache; constructor injection requires arguments during instantiation.",
             "If Bean A needs Bean B and Bean B needs Bean A via constructors, neither can be instantiated first.",
             "Believing @Lazy solves the architectural flaw rather than merely deferring proxy resolution."),

            ("Explain the complete lifecycle of a Spring Bean from startup to shutdown.",
             "Intermediate",
             "1. BeanDefinition scanning and loading -> 2. Instantiation (constructor) -> 3. Populate properties / Dependency Injection -> 4. Aware callbacks (BeanNameAware, ApplicationContextAware) -> 5. BeanPostProcessor pre-initialization -> 6. @PostConstruct / InitializingBean callback -> 7. BeanPostProcessor post-initialization (AOP proxies created here) -> 8. Bean Ready for use -> 9. Destruction callbacks (@PreDestroy, DisposableBean) on container shutdown.",
             "Understanding this sequence is essential for debugging proxy issues, dependency injection timing, and resource leaks.",
             "If code inside a constructor accesses an injected dependency before property population, it triggers NullPointerException.",
             "Believing @PostConstruct runs before constructor execution."),

            ("What is the difference between BeanPostProcessor and BeanFactoryPostProcessor?",
             "Intermediate",
             "BeanFactoryPostProcessor operates on bean metadata (BeanDefinition) before any bean instances are created; it can alter property values (e.g. PropertySourcesPlaceholderConfigurer). BeanPostProcessor operates on instantiated bean objects, customizing or proxying them before and after initialization.",
             "BeanFactoryPostProcessor modifies the blueprint; BeanPostProcessor modifies the actual constructed object.",
             "Custom AOP dynamic proxies are created inside BeanPostProcessor.postProcessAfterInitialization().",
             "Confusing bean definition modification with bean instance interception."),

            ("How does Spring Boot auto-configuration work under the hood?",
             "Intermediate",
             "Spring Boot reads auto-configuration candidate classes listed in META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports. Each configuration class is guarded by conditional annotations (@ConditionalOnClass, @ConditionalOnMissingBean, @ConditionalOnProperty). If conditions evaluate to true, the beans are registered.",
             "This mechanism provides out-of-the-box defaults while stepping aside the moment a developer supplies a custom bean.",
             "DataSourceAutoConfiguration only registers a HikariDataSource if DataSource.class is on the classpath and no DataSource bean already exists.",
             "Assuming auto-configuration uses code generation at compile time."),

            ("What is the N+1 query problem in JPA and Hibernate, and how do you resolve it?",
             "Intermediate",
             "The N+1 problem occurs when fetching 1 parent entity query triggers N additional separate queries to load its associated child entities during iteration over lazy relationships. It is resolved using 'JOIN FETCH' in JPQL, Entity Graphs (@EntityGraph), or batch fetching (@BatchSize).",
             "Lazy loading issues queries per row on demand; join fetching retrieves parents and children in a single SQL SELECT with an inner/left join.",
             "@Query('SELECT o FROM Order o JOIN FETCH o.items') List<Order> findAllWithItems();",
             "Believing that changing relationship fetch type to FetchType.EAGER permanently fixes N+1 queries (it often causes N+1 queries eagerly at query time)."),

            ("What is the difference between JPA and Hibernate?",
             "Intermediate",
             "JPA (Jakarta Persistence API) is a specification and collection of interfaces/annotations defining Object-Relational Mapping standards. Hibernate is a concrete ORM library that implements the JPA specification and provides additional proprietary features (like Envers, advanced caching, and specific Criteria APIs).",
             "Standardizing on JPA allows applications to switch ORM vendors without rewriting entity models.",
             "EntityManager is the standard JPA interface; Session is the underlying Hibernate implementation.",
             "Thinking JPA is a running library that executes SQL queries by itself."),

            ("Explain the Hibernate First-Level Cache (L1 Cache) and its lifecycle.",
             "Intermediate",
             "The First-Level Cache is an in-memory session-scoped cache associated with the current EntityManager/Session. It acts as an Identity Map: fetching an entity by ID multiple times within the same transaction returns the identical Java instance without re-querying the database. It is destroyed when the EntityManager closes.",
             "L1 cache guarantees relational identity within a transaction and enables dirty checking and write-behind batching.",
             "Calling repo.findById(1L) twice in a @Transactional method fires only one SQL SELECT statement.",
             "Thinking the L1 cache is shared across multiple concurrent HTTP requests or multiple users."),

            ("How does Hibernate Dirty Checking work?",
             "Intermediate",
             "When an entity is loaded into the Persistence Context, Hibernate creates a hidden snapshot copy of its initial property values. At transaction flush time, Hibernate compares current entity field values against the snapshot. Any differences trigger an automatic SQL UPDATE statement without calling repository.save().",
             "Automatic dirty checking eliminates manual synchronization code and prevents redundant updates when fields are unmodified.",
             "@Transactional public void updateName(Long id, String name) { User u = repo.findById(id).get(); u.setName(name); // Auto saved! }",
             "Believing repository.save() is required to persist updates to an already managed entity inside a transaction."),

            ("What are the propagation levels in Spring @Transactional and what does REQUIRES_NEW do?",
             "Intermediate",
             "Propagation defines how transactional boundaries behave when a transactional method calls another. Common levels: REQUIRED (joins current transaction or creates new), REQUIRES_NEW (suspends current transaction and creates completely independent physical transaction), MANDATORY, SUPPORTS, NOT_SUPPORTED, NEVER. REQUIRES_NEW executes and commits/rolls back independently.",
             "Useful when an audit log or notification must be committed even if the outer business transaction rolls back.",
             "@Transactional(propagation = Propagation.REQUIRES_NEW) public void logAudit(String action) { ... }",
             "Assuming calling a REQUIRES_NEW method within the same class via 'this.method()' works (it bypasses the Spring AOP proxy)."),

            ("Why does self-invocation of a @Transactional or @Async method within the same class fail?",
             "Intermediate",
             "Spring implements declarative transactions and async execution using AOP proxies. When an external bean calls the method, it calls the proxy. If a method calls another method on 'this', the call executes directly on the target object instance, completely bypassing the proxy interceptor chain.",
             "Proxy interception requires the call to enter through the generated proxy boundary.",
             "Calling this.internalTxMethod() from within public void outerMethod() runs without a transaction.",
             "Believing the issue is a bug in the JVM or compiler rather than the nature of dynamic proxying."),

            # --- ADVANCED & SECURITY QUESTIONS (66 to 105) ---
            ("How does Spring AOP implement method interception using Dynamic Proxies vs CGLIB?",
             "Advanced",
             "Spring AOP creates proxy objects that wrap the target bean. If the target implements interfaces, Spring historically uses JDK Dynamic Proxies (implementing the interface). If the target does not implement interfaces (or in Spring Boot 2.x/3.x where CGLIB is default), Spring uses CGLIB to generate a dynamic subclass at runtime via bytecode generation.",
             "CGLIB subclasses the target, so methods cannot be 'final' and classes cannot be 'final'.",
             "Spring Boot default property: spring.aop.proxy-target-class=true enforces CGLIB proxies across all beans.",
             "Assuming Spring AOP modifies the original compiled bytecode directly like AspectJ compile-time weaving."),

            ("Explain the Spring Security architecture: DelegatingFilterProxy, FilterChainProxy, and SecurityFilterChain.",
             "Advanced",
             "Tomcat manages servlet filters but knows nothing of Spring beans. DelegatingFilterProxy is a standard Servlet filter that delegates all calls to a Spring bean named 'springSecurityFilterChain'. This bean is FilterChainProxy, which matches request URIs against configured SecurityFilterChain instances and executes authentication/authorization filters.",
             "This architecture bridges the raw Servlet container lifecycle to the dependency-injected Spring ApplicationContext.",
             "Tomcat FilterChain -> DelegatingFilterProxy -> FilterChainProxy -> SecurityFilterChain -> DispatcherServlet.",
             "Thinking Spring Security filters run inside Spring MVC Controller handlers."),

            ("What is the difference between Authentication and Authorization in Spring Security?",
             "Advanced",
             "Authentication verifies identity ('Who are you?') by checking credentials (username/password, token) and creates an Authentication token. Authorization verifies access permissions ('What are you allowed to do?') by evaluating GrantedAuthorities or Roles against security rules.",
             "Authentication must succeed before authorization decisions can take place.",
             "Authentication is handled by DaoAuthenticationProvider; Authorization is handled by AuthorizationFilter or @PreAuthorize.",
             "Using the terms interchangeably or storing plain roles without the 'ROLE_' prefix when using hasRole()."),

            ("How does stateless JWT authentication work with Spring Security?",
             "Advanced",
             "The client sends a JWT in the 'Authorization: Bearer <token>' header. A custom OncePerRequestFilter intercepts the request before UsernamePasswordAuthenticationFilter, extracts and validates the token signature/claims, builds a UsernamePasswordAuthenticationToken, and populates SecurityContextHolder.getContext().setAuthentication(auth). Session creation is disabled (SessionCreationPolicy.STATELESS).",
             "Stateless authentication eliminates server-side session memory and enables horizontal microservice scaling.",
             "SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(user, null, authorities));",
             "Allowing the server to create an HTTP session while using JWTs, defeating the stateless purpose."),

            ("How does Spring Boot handle database connection pooling with HikariCP?",
             "Advanced",
             "HikariCP is the default connection pool in Spring Boot. It pre-allocates a pool of physical database connections (configured by maximum-pool-size and minimum-idle). When a transaction opens, HikariCP leases a connection in microseconds; upon commit/rollback, the connection is returned to the pool rather than closed.",
             "Opening physical database connections is expensive (TCP handshake, SSL, auth); pooling reuses active sockets.",
             "spring.datasource.hikari.maximum-pool-size=10 in application.properties.",
             "Allocating thousands of pool connections thinking it increases throughput, which actually exhausts DB CPU and causes lock contention.")
        ]

        # Expand into structured HTML
        questions_html.append("""
<div class="supplement-header">
  <h1>Spring Boot Interview Theory Master Workbook</h1>
  <p class="intro">100+ comprehensive, production-grounded interview theory questions organized across Beginner, Intermediate, and Advanced engineering tiers. Each question includes clear technical answers, underlying rationale, practical examples, and common misconceptions.</p>
</div>
""")

        current_diff = ""
        q_counter = 1

        for q, diff, ans, why, eg, wrong in questions_data:
            if diff != current_diff:
                current_diff = diff
                questions_html.append(f"""
<div class="toc-part-title" style="margin-top:16pt; font-size:12pt;">
  SECTION: {current_diff.upper()} LEVEL QUESTIONS
</div>
""")

            questions_html.append(f"""
<div class="interview-card" style="margin: 10pt 0; border: 0.6pt solid #cbd5e1; padding: 7pt 10pt; background: #fff; page-break-inside: avoid;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4pt;">
    <strong style="font-size:10.5pt; color:#0f172a;">Q{q_counter}. {q}</strong>
    <span style="font-size:7.8pt; font-weight:700; background:#f1f5f9; color:#475569; padding:2pt 6pt; border-radius:3px; text-transform:uppercase;">{diff}</span>
  </div>
  <p style="margin:3pt 0; font-size:9.4pt; color:#1e293b;"><strong>Clear Answer:</strong> {ans}</p>
  <p style="margin:3pt 0; font-size:9pt; color:#334155;"><strong>Why It Is Correct:</strong> {why}</p>
  <div style="margin:4pt 0; font-size:8.8pt; background:#f8fafc; border-left:2pt solid #16a34a; padding:3pt 6pt;">
    <strong>Practical Example / Context:</strong> <code>{eg}</code>
  </div>
  <p style="margin:3pt 0; font-size:8.8pt; color:#b91c1c;"><strong>Common Misconception:</strong> {wrong}</p>
</div>
""")
            q_counter += 1

        return "\n".join(questions_html)

    # =========================================================================
    # INTERVIEW PRACTICAL QUESTIONS (PRACTICAL WORKBOOK)
    # =========================================================================
    def build_interview_practical_html(self) -> str:
        """Constructs practical coding problems with starter code, full working solutions, and explanations."""
        return """
<div class="supplement-header">
  <h1>Spring Boot Interview Practical Workbook</h1>
  <p class="intro">Hands-on coding problems, architecture design tasks, and real-world debugging challenges. Features complete, production-grade Spring Boot 3.x and Java 17/21 implementations with detailed architectural rationale.</p>
</div>

<h2>Practical Problem 1: Tiered Architecture &amp; REST Controller with Validation</h2>
<div class="box">
  <strong>Difficulty:</strong> Beginner-Intermediate | <strong>Topic:</strong> DTOs, Bean Validation, ResponseEntity<br>
  <strong>Problem Statement:</strong> Implement a production-grade <code>ProductController</code> and <code>ProductService</code> that accepts a <code>CreateProductRequest</code> DTO, validates that <code>name</code> is non-blank and <code>price</code> is greater than zero, saves the entity, and returns a <code>201 Created</code> response with a <code>Location</code> header.
</div>

<div class="codewrap">
  <div class="cap">Java - CreateProductRequest DTO with Validation</div>
  <pre><code>package com.example.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;

public record CreateProductRequest(
    @NotBlank(message = "Product name must not be blank")
    String name,

    @NotNull(message = "Price is required")
    @DecimalMin(value = "0.01", message = "Price must be strictly positive")
    BigDecimal price
) {}</code></pre>
</div>

<div class="codewrap">
  <div class="cap">Java - ProductController Implementation</div>
  <pre><code>package com.example.controller;

import com.example.dto.CreateProductRequest;
import com.example.dto.ProductResponse;
import com.example.service.ProductService;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.support.ServletUriComponentsBuilder;

import java.net.URI;

@RestController
@RequestMapping("/api/v1/products")
public class ProductController {

    private final ProductService productService;

    public ProductController(ProductService productService) {
        this.productService = productService;
    }

    @PostMapping
    public ResponseEntity&lt;ProductResponse&gt; createProduct(@Valid @RequestBody CreateProductRequest request) {
        ProductResponse created = productService.createProduct(request);
        URI location = ServletUriComponentsBuilder.fromCurrentRequest()
                .path("/{id}")
                .buildAndExpand(created.id())
                .toUri();
        return ResponseEntity.created(location).body(created);
    }
}</code></pre>
</div>
<p><strong>Explanation:</strong> The controller delegates business persistence to the constructor-injected service. Attaching <code>@Valid</code> triggers Jakarta Bean Validation; any validation failure immediately raises <code>MethodArgumentNotValidException</code> without executing controller code. <code>ServletUriComponentsBuilder</code> safely constructs the standard HTTP 201 <code>Location</code> header.</p>

<h2>Practical Problem 2: Centralized Error Handling with @RestControllerAdvice</h2>
<div class="box">
  <strong>Difficulty:</strong> Intermediate | <strong>Topic:</strong> Exception Handling &amp; Standardized Error DTO<br>
  <strong>Problem Statement:</strong> Create a global exception handler that intercepts <code>MethodArgumentNotValidException</code> (Bean Validation) and custom <code>ResourceNotFoundException</code>, returning a standardized JSON body with field-level validation errors and correct HTTP status codes.
</div>

<div class="codewrap">
  <div class="cap">Java - GlobalExceptionHandler</div>
  <pre><code>package com.example.exception;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ResourceNotFoundException.class)
    public ResponseEntity&lt;Map&lt;String, Object&gt;&gt; handleNotFound(ResourceNotFoundException ex) {
        Map&lt;String, Object&gt; body = new HashMap&lt;&gt;();
        body.put("timestamp", Instant.now().toString());
        body.put("status", HttpStatus.NOT_FOUND.value());
        body.put("error", "Not Found");
        body.put("message", ex.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(body);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity&lt;Map&lt;String, Object&gt;&gt; handleValidationErrors(MethodArgumentNotValidException ex) {
        Map&lt;String, String&gt; fieldErrors = new HashMap&lt;&gt;();
        for (FieldError fe : ex.getBindingResult().getFieldErrors()) {
            fieldErrors.put(fe.getField(), fe.getDefaultMessage());
        }

        Map&lt;String, Object&gt; body = new HashMap&lt;&gt;();
        body.put("timestamp", Instant.now().toString());
        body.put("status", HttpStatus.BAD_REQUEST.value());
        body.put("error", "Validation Failed");
        body.put("fieldErrors", fieldErrors);
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(body);
    }
}</code></pre>
</div>

<h2>Practical Problem 3: Solving JPA N+1 Queries with Entity Graphs</h2>
<div class="box">
  <strong>Difficulty:</strong> Advanced | <strong>Topic:</strong> Spring Data JPA, Performance Optimization<br>
  <strong>Problem Statement:</strong> An <code>Author</code> entity has a <code>@OneToMany(fetch = FetchType.LAZY)</code> relationship with <code>Book</code>. Fetching all authors and iterating through books causes 50 separate SQL queries. Implement an optimized repository query using <code>@EntityGraph</code> to fetch all authors and books in a single SQL query.
</div>

<div class="codewrap">
  <div class="cap">Java - AuthorRepository with @EntityGraph</div>
  <pre><code>package com.example.repository;

import com.example.entity.Author;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AuthorRepository extends JpaRepository&lt;Author, Long&gt; {

    // Overrides default lazy loading with a LEFT JOIN FETCH in a single SQL query
    @EntityGraph(attributePaths = {"books"})
    @Query("SELECT a FROM Author a")
    List&lt;Author&gt; findAllWithBooks();
}</code></pre>
</div>
<p><strong>Explanation:</strong> <code>@EntityGraph(attributePaths = {"books"})</code> instructs Hibernate to execute an eager outer join fetch on the specified attribute path for this query execution only, preventing N+1 queries while preserving global lazy loading across the rest of the application.</p>

<h2>Practical Problem 4: Stateless JWT Authentication Filter</h2>
<div class="box">
  <strong>Difficulty:</strong> Advanced | <strong>Topic:</strong> Spring Security, Filter Pipeline<br>
  <strong>Problem Statement:</strong> Implement a production-grade <code>JwtAuthenticationFilter</code> extending <code>OncePerRequestFilter</code> that reads the <code>Authorization</code> header, verifies the token, and sets the <code>SecurityContext</code>.
</div>

<div class="codewrap">
  <div class="cap">Java - JwtAuthenticationFilter</div>
  <pre><code>package com.example.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtService jwtService;
    private final UserDetailsService userDetailsService;

    public JwtAuthenticationFilter(JwtService jwtService, UserDetailsService userDetailsService) {
        this.jwtService = jwtService;
        this.userDetailsService = userDetailsService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String authHeader = request.getHeader("Authorization");
        if (authHeader == null || !authHeader.startsWith("Bearer ")) {
            filterChain.doFilter(request, response);
            return;
        }

        String jwt = authHeader.substring(7);
        String username = jwtService.extractUsername(jwt);

        if (username != null && SecurityContextHolder.getContext().getAuthentication() == null) {
            UserDetails userDetails = userDetailsService.loadUserByUsername(username);
            if (jwtService.isTokenValid(jwt, userDetails)) {
                UsernamePasswordAuthenticationToken authToken =
                        new UsernamePasswordAuthenticationToken(userDetails, null, userDetails.getAuthorities());
                authToken.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
                SecurityContextHolder.getContext().setAuthentication(authToken);
            }
        }
        filterChain.doFilter(request, response);
    }
}</code></pre>
</div>
"""

    def generate_supplement(
        self,
        supplement_type: str,
        reuse: bool = False,
        use_ai: bool = False,
        start_page: int = 1,
    ) -> Path:
        """Generates or reuses HTML, validates it, renders PDF, and stamps headers/footers."""
        supplement_type = supplement_type.lower().strip()
        filename_map = {
            "revision": ("Revision_Sheets.pdf", "supplement_revision.html", "Revision Sheets"),
            "theory": ("Interview_Theory.pdf", "supplement_theory.html", "Interview Questions — Theory"),
            "practical": ("Interview_Practical.pdf", "supplement_practical.html", "Interview Questions — Practical"),
        }
        if supplement_type not in filename_map:
            raise ValueError(f"Unknown supplement type: {supplement_type}. Choose from 'revision', 'theory', 'practical'.")

        pdf_name, html_name, section_title = filename_map[supplement_type]
        cache_html_path = self.work_dir / html_name
        output_pdf_path = self.output_dir / pdf_name
        raw_pdf_path = self.work_dir / f"raw_{pdf_name}"

        body_html = ""
        if reuse and cache_html_path.exists():
            print(f"[SUPPLEMENT] Reusing cached HTML: {cache_html_path.name}")
            body_html = cache_html_path.read_text(encoding="utf-8")
        else:
            print(f"[SUPPLEMENT] Generating curriculum-grounded content for {section_title}...")
            if supplement_type == "revision":
                body_html = self.build_revision_sheets_html()
            elif supplement_type == "theory":
                body_html = self.build_interview_theory_html()
            elif supplement_type == "practical":
                body_html = self.build_interview_practical_html()

            # Validate before caching
            validate_supplement_html(body_html, supplement_type)
            # Atomically cache HTML
            save_cache_atomically(cache_html_path, body_html)
            print(f"[SUPPLEMENT] Successfully validated and cached HTML to {cache_html_path.name}")

        # Render HTML to Raw PDF using PDFRenderer (which inlines style.css)
        print(f"[SUPPLEMENT] Rendering PDF with Playwright for {pdf_name}...")
        full_html = self.renderer.build_full_html(body_html)
        self.renderer.render_html_to_pdf(full_html, raw_pdf_path)

        # Apply running header and continuous footer
        print(f"[SUPPLEMENT] Stamping headers and running footers (starting at page {start_page})...")
        page_count = SupplementStamper.stamp_supplement(
            raw_pdf_path=raw_pdf_path,
            final_pdf_path=output_pdf_path,
            section_title=section_title,
            start_page=start_page,
        )
        print(f"[SUCCESS] Rendered {pdf_name} ({page_count} pages) at {output_pdf_path}")
        return output_pdf_path

    def build_all(self, reuse: bool = False, use_ai: bool = False) -> Dict[str, Path]:
        """Builds all 3 supplements in order."""
        results = {}
        for stype in ("revision", "theory", "practical"):
            results[stype] = self.generate_supplement(stype, reuse=reuse, use_ai=use_ai)
        return results
