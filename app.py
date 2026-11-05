from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from functools import wraps
import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional, List, Tuple, Dict

try:
    from flask_socketio import SocketIO, join_room
except Exception:  # pragma: no cover
    SocketIO = None

    def join_room(*_args, **_kwargs):
        return None

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
except Exception:  # pragma: no cover
    BackgroundScheduler = None
    IntervalTrigger = None

try:
    from pywebpush import webpush, WebPushException
except Exception:  # pragma: no cover
    webpush = None
    WebPushException = Exception

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///job_portal.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads/resumes'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600  # 1 hour cache for static files

# Performance optimizations
app.config['COMPRESS_REGISTER'] = False  # Disable Flask-Compress if installed
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False  # Minify JSON responses

# Email (SMTP) - configure via environment variables
app.config['SMTP_HOST'] = os.environ.get('SMTP_HOST', '')
app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', '587'))
app.config['SMTP_USER'] = os.environ.get('SMTP_USER', '')
app.config['SMTP_PASSWORD'] = os.environ.get('SMTP_PASSWORD', '')
app.config['SMTP_USE_TLS'] = os.environ.get('SMTP_USE_TLS', 'true').lower() == 'true'
app.config['EMAIL_FROM'] = os.environ.get('EMAIL_FROM', app.config['SMTP_USER'] or 'no-reply@example.com')

# Web Push (VAPID) - configure via environment variables
app.config['VAPID_PUBLIC_KEY'] = os.environ.get('VAPID_PUBLIC_KEY', '')
app.config['VAPID_PRIVATE_KEY'] = os.environ.get('VAPID_PRIVATE_KEY', '')
app.config['VAPID_CLAIMS_SUB'] = os.environ.get('VAPID_CLAIMS_SUB', 'mailto:admin@example.com')

# Scheduler (cron-like) configuration
app.config['ALERT_MATCH_INTERVAL_MINUTES'] = int(os.environ.get('ALERT_MATCH_INTERVAL_MINUTES', '15'))

# Ensure upload directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# Socket.IO for real-time notifications (optional)
socketio = None
if SocketIO is not None:
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

logging.basicConfig(level=logging.INFO)

# Background scheduler (cron-like) (optional)
scheduler = None
if BackgroundScheduler is not None:
    scheduler = BackgroundScheduler(daemon=True)

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resume_path = db.Column(db.String(255))

    applications = db.relationship('Application', backref='user', lazy='dynamic')
    job_alerts = db.relationship('JobAlert', backref='user', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')
    push_subscriptions = db.relationship('PushSubscription', backref='user', lazy='dynamic')

class Job(db.Model):
    __table_args__ = (
        db.Index('ix_job_is_active', 'is_active'),
        db.Index('ix_job_created_at', 'created_at'),
        db.Index('ix_job_category', 'job_category'),
        db.Index('ix_job_category_active', 'job_category', 'is_active'),
        db.Index('ix_job_category_active_created', 'job_category', 'is_active', 'created_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    job_type = db.Column(db.String(50))  # Full-time, Part-time, Contract, etc.
    category = db.Column(db.String(100))  # IT, Healthcare, Education, etc.
    job_category = db.Column(db.String(50))  # Government or Private
    description = db.Column(db.Text, nullable=False)
    requirements = db.Column(db.Text)
    salary_min = db.Column(db.Float)
    salary_max = db.Column(db.Float)
    experience_required = db.Column(db.String(50))
    posted_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    deadline = db.Column(db.DateTime)
    
    # Government Job Specific Fields
    age_limit = db.Column(db.String(100))  # e.g., "18-30 years", "21-35 years"
    exam_pattern = db.Column(db.Text)  # Exam pattern and selection stages
    official_notification_link = db.Column(db.String(500))  # Link to official PDF
    official_website_link = db.Column(db.String(500))  # Link to official application website
    application_start_date = db.Column(db.DateTime)  # When applications start
    application_end_date = db.Column(db.DateTime)  # When applications end
    pay_scale = db.Column(db.String(200))  # Pay scale for government jobs (e.g., "Level 5, Rs. 29,200 - Rs. 92,300")
    
    applications = db.relationship('Application', backref='job', lazy=True)

class Application(db.Model):
    __table_args__ = (
        db.Index('ix_application_user_id', 'user_id'),
        db.Index('ix_application_job_id', 'job_id'),
        db.Index('ix_application_status', 'status'),
        db.Index('ix_application_user_status', 'user_id', 'status'),
        db.Index('ix_application_applied_at', 'applied_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    status = db.Column(db.String(50), default='Pending')  # Pending, Shortlisted, Rejected, Accepted
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    cover_letter = db.Column(db.Text)

class JobAlert(db.Model):
    __table_args__ = (
        db.Index('ix_job_alert_user_id', 'user_id'),
        db.Index('ix_job_alert_is_active', 'is_active'),
        db.Index('ix_job_alert_user_active', 'user_id', 'is_active'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keywords = db.Column(db.String(200))
    location = db.Column(db.String(100))
    job_category = db.Column(db.String(50))  # Government or Private
    category = db.Column(db.String(100))  # Job category
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_checked_at = db.Column(db.DateTime)  # used by scheduler to only match new jobs

class Notification(db.Model):
    __table_args__ = (
        db.Index('ix_notification_user_read', 'user_id', 'is_read'),
        db.Index('ix_notification_user_created', 'user_id', 'created_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False, index=True)  # e.g., application_status, job_match
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Optional references
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=True, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey('application.id'), nullable=True, index=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('job_alert.id'), nullable=True, index=True)

    # NOTE: We don't rely on a UNIQUE constraint here because SQLite treats NULLs as distinct
    # in UNIQUE constraints, which would allow duplicates when some reference columns are NULL.

class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    endpoint = db.Column(db.String(500), nullable=False, unique=True)
    p256dh = db.Column(db.String(250), nullable=False)
    auth = db.Column(db.String(250), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

if socketio is not None:
    @socketio.on('connect')
    def socket_connect():
        if current_user.is_authenticated:
            join_room(f"user_{current_user.id}")

def _smtp_configured():
    return bool(app.config.get('SMTP_HOST')) and bool(app.config.get('EMAIL_FROM'))

def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email via SMTP. Returns True on success, False otherwise."""
    if not _smtp_configured():
        return False
    try:
        msg = EmailMessage()
        msg["From"] = app.config["EMAIL_FROM"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(app.config["SMTP_HOST"], app.config["SMTP_PORT"], timeout=15) as server:
            server.ehlo()
            if app.config["SMTP_USE_TLS"]:
                server.starttls(context=context)
                server.ehlo()
            if app.config["SMTP_USER"] and app.config["SMTP_PASSWORD"]:
                server.login(app.config["SMTP_USER"], app.config["SMTP_PASSWORD"])
            server.send_message(msg)
        return True
    except Exception as e:
        logging.exception(f"Email send failed: {e}")
        return False

def _push_configured():
    return bool(app.config.get('VAPID_PUBLIC_KEY')) and bool(app.config.get('VAPID_PRIVATE_KEY')) and webpush is not None

def send_web_push(subscription: PushSubscription, title: str, message: str, url: str = "/") -> bool:
    """Send a web push notification to a stored subscription."""
    if not _push_configured():
        return False
    try:
        payload = json.dumps({"title": title, "message": message, "url": url})
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=app.config["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": app.config["VAPID_CLAIMS_SUB"]},
        )
        return True
    except WebPushException as e:
        logging.warning(f"Web push failed: {e}")
        return False
    except Exception as e:
        logging.exception(f"Web push error: {e}")
        return False

def create_notification(
    *,
    user_id: int,
    type: str,
    title: str,
    message: str,
    job_id: Optional[int] = None,
    application_id: Optional[int] = None,
    alert_id: Optional[int] = None,
    emit_realtime: bool = True,
    send_email_now: bool = False,
    push_now: bool = False,
):
    """Create a notification (deduped) and optionally deliver."""
    existing = Notification.query.filter_by(
        user_id=user_id,
        type=type,
        job_id=job_id,
        application_id=application_id,
        alert_id=alert_id,
    ).first()
    if existing:
        return existing

    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        job_id=job_id,
        application_id=application_id,
        alert_id=alert_id,
        is_read=False,
    )
    try:
        db.session.add(notification)
        db.session.commit()
    except Exception:
        db.session.rollback()
        # best-effort: skip on any error
        return None

    if emit_realtime and socketio is not None:
        socketio.emit(
            "notification",
            {
                "id": notification.id,
                "type": notification.type,
                "title": notification.title,
                "message": notification.message,
                "created_at": notification.created_at.isoformat(),
                "is_read": notification.is_read,
            },
            room=f"user_{user_id}",
        )

    # Send emails asynchronously to avoid blocking response
    if user_id and send_email_now:
        import threading
        def _send_email_async():
            user = User.query.get(user_id)
            if user and user.email:
                send_email(user.email, f"[Job Portal] {title}", f"{message}\n\nLogin: http://localhost:5000/dashboard")
        threading.Thread(target=_send_email_async, daemon=True).start()

    if push_now:
        import threading
        def _send_push_async():
            subs = PushSubscription.query.filter_by(user_id=user_id).all()
            for sub in subs:
                send_web_push(sub, title=title, message=message, url="/dashboard")
        threading.Thread(target=_send_push_async, daemon=True).start()

    return notification

def _normalize_keywords(s: Optional[str]) -> List[str]:
    if not s:
        return []
    # split on commas first, then spaces
    parts = []
    for chunk in s.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts.extend([p.strip() for p in chunk.split() if p.strip()])
    # de-dupe while preserving order
    seen = set()
    out = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out

def score_job_against_alert(job: Job, alert: JobAlert) -> Tuple[int, List[str]]:
    """
    Simple matching algorithm (0-100) for job-alert comparison.
    Returns (score, reasons).
    """
    score = 0
    reasons: List[str] = []

    # Hard filters (when provided)
    if alert.job_category and (job.job_category != alert.job_category):
        return 0, ["job_category_mismatch"]
    if alert.category and (job.category != alert.category):
        return 0, ["category_mismatch"]
    if alert.location:
        if alert.location.lower() not in (job.location or "").lower():
            return 0, ["location_mismatch"]
        score += 20
        reasons.append("location_match")

    # Keywords matching (soft scoring)
    haystack = " ".join([
        job.title or "",
        job.company or "",
        job.description or "",
        job.requirements or "",
    ]).lower()
    keywords = _normalize_keywords(alert.keywords)
    if keywords:
        matched = 0
        for kw in keywords:
            if kw.lower() in haystack:
                matched += 1
        if matched == 0:
            return 0, ["no_keyword_match"]
        # up to 60 points from keywords
        kw_score = int(min(60, round(60 * (matched / max(len(keywords), 1)))))
        score += kw_score
        reasons.append(f"keywords_{matched}_of_{len(keywords)}")
    else:
        # no keywords: still allow matching via category/location filters
        score += 20
        reasons.append("no_keywords_provided")

    # Category presence bonus (if alert specified)
    if alert.category:
        score += 10
        reasons.append("category_match")
    if alert.job_category:
        score += 10
        reasons.append("job_category_match")

    return min(score, 100), reasons

def match_alerts_for_job(job: Job) -> int:
    """Match a single job against active alerts and create notifications. Returns count created."""
    if not job or not job.is_active:
        return 0

    created = 0
    alerts = JobAlert.query.filter_by(is_active=True).all()
    # Pre-load all users to avoid N+1 queries
    alert_user_ids = {a.user_id for a in alerts}
    users_by_id = {u.id: u for u in User.query.filter(User.id.in_(alert_user_ids)).all()}
    for alert in alerts:
        user = users_by_id.get(alert.user_id)
        if not user:
            continue
        score, _reasons = score_job_against_alert(job, alert)
        if score <= 0:
            continue

        n = create_notification(
            user_id=alert.user_id,
            type="job_match",
            title="New job match",
            message=f"Matched job: {job.title} at {job.company} ({job.location}). Match score: {score}%",
            job_id=job.id,
            alert_id=alert.id,
            emit_realtime=True,
            send_email_now=True,
            push_now=True,
        )
        if n is not None:
            created += 1
    return created

def run_job_alert_matching() -> Dict[str, int]:
    """
    Scheduled matching job:
    - For each active alert, find jobs created since last_checked_at (or alert.created_at)
    - Score + notify
    - Update last_checked_at
    """
    stats = {"alerts_checked": 0, "jobs_scanned": 0, "notifications_created": 0}
    now = datetime.utcnow()

    alerts = JobAlert.query.filter_by(is_active=True).all()
    # Pre-load all users to avoid N+1 queries
    alert_user_ids = {a.user_id for a in alerts}
    users_by_id = {u.id: u for u in User.query.filter(User.id.in_(alert_user_ids)).all()}
    for alert in alerts:
        stats["alerts_checked"] += 1
        since = alert.last_checked_at or alert.created_at or now
        user = users_by_id.get(alert.user_id)
        if not user:
            continue

        # only scan new-ish jobs since last check
        jobs_q = Job.query.filter(Job.is_active == True, Job.created_at >= since)  # noqa: E712
        # apply strict filters early when possible
        if alert.job_category:
            jobs_q = jobs_q.filter(Job.job_category == alert.job_category)
        if alert.category:
            jobs_q = jobs_q.filter(Job.category == alert.category)
        if alert.location:
            jobs_q = jobs_q.filter(Job.location.contains(alert.location))

        jobs_list = jobs_q.order_by(Job.created_at.desc()).limit(200).all()
        stats["jobs_scanned"] += len(jobs_list)
        for job in jobs_list:
            score, _reasons = score_job_against_alert(job, alert)
            if score <= 0:
                continue
            n = create_notification(
                user_id=alert.user_id,
                type="job_match",
                title="New job match",
                message=f"Matched job: {job.title} at {job.company} ({job.location}). Match score: {score}%",
                job_id=job.id,
                alert_id=alert.id,
                emit_realtime=True,
                send_email_now=True,
                push_now=True,
            )
            if n is not None:
                stats["notifications_created"] += 1

        alert.last_checked_at = now
        db.session.commit()

    return stats

def start_scheduler():
    """Start background scheduler safely (avoid double start in debug reloader)."""
    if scheduler is None or IntervalTrigger is None:
        logging.info("[scheduler] APScheduler not installed; scheduler is disabled.")
        return
    if scheduler.running:
        return
    # Don't start scheduler in debug mode to avoid double execution
    if app.debug:
        logging.info("[scheduler] Skipping scheduler in debug mode")
        return
    interval = max(int(app.config.get("ALERT_MATCH_INTERVAL_MINUTES", 15)), 1)

    def _job_wrapper():
        with app.app_context():
            try:
                stats = run_job_alert_matching()
                logging.info(f"[scheduler] job-alert matching stats: {stats}")
            except Exception as e:
                logging.exception(f"[scheduler] matching failed: {e}")

    scheduler.add_job(
        _job_wrapper,
        trigger=IntervalTrigger(minutes=interval),
        id="job_alert_matching",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    jobs = Job.query.filter_by(is_active=True).order_by(Job.created_at.desc()).limit(10).all()
    return render_template('index.html', jobs=jobs)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            full_name=full_name,
            phone=phone
        )
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Redirect admins to admin login if they try to use regular login
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            # Redirect admins to admin dashboard
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    user_applications = Application.query.filter_by(user_id=current_user.id).order_by(Application.applied_at.desc()).paginate(page=page, per_page=10, error_out=False)
    return render_template('dashboard.html', applications=user_applications)

@app.route('/jobs')
def jobs():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    job_category = request.args.get('job_category', '')
    category = request.args.get('category', '')
    location = request.args.get('location', '')
    job_type = request.args.get('job_type', '')
    
    query = Job.query.filter_by(is_active=True)
    
    if search:
        query = query.filter(
            db.or_(
                Job.title.contains(search),
                Job.company.contains(search),
                Job.description.contains(search)
            )
        )
    
    if job_category:
        query = query.filter_by(job_category=job_category)
    
    if category:
        query = query.filter_by(category=category)
    
    if location:
        query = query.filter(Job.location.contains(location))
    
    if job_type:
        query = query.filter_by(job_type=job_type)
    
    jobs = query.order_by(Job.created_at.desc()).paginate(page=page, per_page=10, error_out=False)
    
    return render_template('jobs.html', jobs=jobs, search=search, job_category=job_category, 
                         category=category, location=location, job_type=job_type)

@app.route('/job/<int:job_id>')
def job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    has_applied = False
    if current_user.is_authenticated:
        has_applied = Application.query.filter_by(user_id=current_user.id, job_id=job_id).first() is not None
    return render_template('job_detail.html', job=job, has_applied=has_applied)

@app.route('/apply/<int:job_id>', methods=['GET', 'POST'])
@login_required
def apply_job(job_id):
    job = Job.query.get_or_404(job_id)
    
    # Government jobs redirect to official website
    if job.job_category == 'Government':
        if job.official_website_link:
            flash('Redirecting to official government website for application...', 'info')
            return redirect(job.official_website_link)
        else:
            flash('Official application website link not available. Please contact the department directly.', 'warning')
            return redirect(url_for('job_detail', job_id=job_id))
    
    # Private jobs - normal application process
    if Application.query.filter_by(user_id=current_user.id, job_id=job_id).first():
        flash('You have already applied for this job.', 'warning')
        return redirect(url_for('job_detail', job_id=job_id))
    
    if request.method == 'POST':
        cover_letter = request.form.get('cover_letter', '')
        application = Application(
            user_id=current_user.id,
            job_id=job_id,
            cover_letter=cover_letter
        )
        db.session.add(application)
        db.session.commit()
        flash('Application submitted successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('apply_job.html', job=job)

@app.route('/upload_resume', methods=['GET', 'POST'])
@login_required
def upload_resume():
    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(url_for('upload_resume'))
        
        file = request.files['resume']
        if file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('upload_resume'))
        
        if file and allowed_file(file.filename):
            filename = secure_filename(f"{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Delete old resume if exists
            if current_user.resume_path:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], current_user.resume_path)
                if os.path.exists(old_path):
                    os.remove(old_path)
            
            current_user.resume_path = filename
            db.session.commit()
            flash('Resume uploaded successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid file type. Please upload PDF, DOC, or DOCX files only.', 'danger')
    
    return render_template('upload_resume.html')

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/download_resume/<filename>')
@login_required
def download_resume(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Notification API ---
@app.route('/api/notifications', methods=['GET'])
@login_required
def api_notifications_list():
    limit = request.args.get('limit', 10, type=int)
    items = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(min(max(limit, 1), 50))
        .all()
    )
    return jsonify([
        {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "message": n.message,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
        }
        for n in items
    ])

@app.route('/api/notifications/unread_count', methods=['GET'])
@login_required
def api_notifications_unread_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({"unread": count})

@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def api_notifications_mark_read(notification_id):
    n = Notification.query.get_or_404(notification_id)
    if n.user_id != current_user.id:
        return jsonify({"error": "unauthorized"}), 403
    n.is_read = True
    db.session.commit()
    return jsonify({"ok": True})

@app.route('/api/notifications/read_all', methods=['POST'])
@login_required
def api_notifications_mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True})

# --- Push subscription API ---
@app.route('/api/push/public_key', methods=['GET'])
@login_required
def api_push_public_key():
    return jsonify({"publicKey": app.config.get("VAPID_PUBLIC_KEY", "")})

@app.route('/api/push/subscribe', methods=['POST'])
@login_required
def api_push_subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not endpoint or not p256dh or not auth:
        return jsonify({"error": "invalid_subscription"}), 400

    existing = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if existing:
        existing.user_id = current_user.id
        existing.p256dh = p256dh
        existing.auth = auth
    else:
        db.session.add(PushSubscription(user_id=current_user.id, endpoint=endpoint, p256dh=p256dh, auth=auth))
    db.session.commit()
    return jsonify({"ok": True})

@app.route('/api/push/unsubscribe', methods=['POST'])
@login_required
def api_push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    if not endpoint:
        return jsonify({"error": "missing_endpoint"}), 400
    PushSubscription.query.filter_by(endpoint=endpoint, user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})

# Service worker needs to be at /sw.js for widest scope
@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js')

@app.route('/job_alerts', methods=['GET', 'POST'])
@login_required
def job_alerts():
    if request.method == 'POST':
        keywords = request.form.get('keywords', '')
        location = request.form.get('location', '')
        job_category = request.form.get('job_category', '')
        category = request.form.get('category', '')
        
        alert = JobAlert(
            user_id=current_user.id,
            keywords=keywords,
            location=location,
            job_category=job_category,
            category=category
        )
        db.session.add(alert)
        db.session.commit()
        flash('Job alert created successfully!', 'success')
        return redirect(url_for('job_alerts'))
    
    page = request.args.get('page', 1, type=int)
    alerts = JobAlert.query.filter_by(user_id=current_user.id).order_by(JobAlert.created_at.desc()).paginate(page=page, per_page=10, error_out=False)
    return render_template('job_alerts.html', alerts=alerts)

@app.route('/delete_alert/<int:alert_id>')
@login_required
def delete_alert(alert_id):
    alert = JobAlert.query.get_or_404(alert_id)
    if alert.user_id != current_user.id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('job_alerts'))
    
    db.session.delete(alert)
    db.session.commit()
    flash('Job alert deleted.', 'success')
    return redirect(url_for('job_alerts'))

# Admin Routes
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_jobs = db.session.execute(db.select(db.func.count()).select_from(Job)).scalar()
    active_jobs = db.session.execute(db.select(db.func.count()).select_from(Job).where(Job.is_active == True)).scalar()
    total_applications = db.session.execute(db.select(db.func.count()).select_from(Application)).scalar()
    total_users = db.session.execute(db.select(db.func.count()).select_from(User)).scalar()
    
    stats = {
        'total_jobs': total_jobs,
        'active_jobs': active_jobs,
        'total_applications': total_applications,
        'total_users': total_users
    }
    
    return render_template('admin/dashboard.html', stats=stats)

@app.route('/admin/jobs')
@login_required
@admin_required
def admin_jobs():
    page = request.args.get('page', 1, type=int)
    jobs = Job.query.order_by(Job.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/jobs.html', jobs=jobs)

@app.route('/admin/job/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_job():
    if request.method == 'POST':
        job_category = request.form.get('job_category')
        
        job = Job(
            title=request.form.get('title'),
            company=request.form.get('company'),
            location=request.form.get('location'),
            job_type=request.form.get('job_type'),
            category=request.form.get('category'),
            job_category=job_category,
            description=request.form.get('description'),
            requirements=request.form.get('requirements'),
            salary_min=float(request.form.get('salary_min')) if request.form.get('salary_min') else None,
            salary_max=float(request.form.get('salary_max')) if request.form.get('salary_max') else None,
            experience_required=request.form.get('experience_required'),
            posted_by=current_user.id,
            deadline=datetime.strptime(request.form.get('deadline'), '%Y-%m-%d') if request.form.get('deadline') else None
        )
        
        # Government job specific fields
        if job_category == 'Government':
            job.age_limit = request.form.get('age_limit')
            job.exam_pattern = request.form.get('exam_pattern')
            job.official_notification_link = request.form.get('official_notification_link')
            job.official_website_link = request.form.get('official_website_link')
            job.pay_scale = request.form.get('pay_scale')
            if request.form.get('application_start_date'):
                job.application_start_date = datetime.strptime(request.form.get('application_start_date'), '%Y-%m-%d')
            if request.form.get('application_end_date'):
                job.application_end_date = datetime.strptime(request.form.get('application_end_date'), '%Y-%m-%d')
        
        db.session.add(job)
        db.session.commit()
        flash('Job posted successfully!', 'success')

        # Immediately run matching for this job (real-time job alerts)
        try:
            match_alerts_for_job(job)
        except Exception as e:
            logging.exception(f"Job alert matching failed: {e}")

        return redirect(url_for('admin_jobs'))
    
    return render_template('admin/add_job.html')

@app.route('/admin/job/<int:job_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_job(job_id):
    job = Job.query.get_or_404(job_id)
    
    if request.method == 'POST':
        job.title = request.form.get('title')
        job.company = request.form.get('company')
        job.location = request.form.get('location')
        job.job_type = request.form.get('job_type')
        job.category = request.form.get('category')
        job_category = request.form.get('job_category')
        job.job_category = job_category
        job.description = request.form.get('description')
        job.requirements = request.form.get('requirements')
        job.salary_min = float(request.form.get('salary_min')) if request.form.get('salary_min') else None
        job.salary_max = float(request.form.get('salary_max')) if request.form.get('salary_max') else None
        job.experience_required = request.form.get('experience_required')
        job.is_active = request.form.get('is_active') == 'on'
        if request.form.get('deadline'):
            job.deadline = datetime.strptime(request.form.get('deadline'), '%Y-%m-%d')
        
        # Government job specific fields
        if job_category == 'Government':
            job.age_limit = request.form.get('age_limit')
            job.exam_pattern = request.form.get('exam_pattern')
            job.official_notification_link = request.form.get('official_notification_link')
            job.official_website_link = request.form.get('official_website_link')
            job.pay_scale = request.form.get('pay_scale')
            if request.form.get('application_start_date'):
                job.application_start_date = datetime.strptime(request.form.get('application_start_date'), '%Y-%m-%d')
            else:
                job.application_start_date = None
            if request.form.get('application_end_date'):
                job.application_end_date = datetime.strptime(request.form.get('application_end_date'), '%Y-%m-%d')
            else:
                job.application_end_date = None
        else:
            # Clear government fields if changed to private
            job.age_limit = None
            job.exam_pattern = None
            job.official_notification_link = None
            job.official_website_link = None
            job.pay_scale = None
            job.application_start_date = None
            job.application_end_date = None
        
        db.session.commit()
        flash('Job updated successfully!', 'success')
        return redirect(url_for('admin_jobs'))
    
    return render_template('admin/edit_job.html', job=job)

@app.route('/admin/job/<int:job_id>/delete')
@login_required
@admin_required
def admin_delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    flash('Job deleted successfully!', 'success')
    return redirect(url_for('admin_jobs'))

@app.route('/admin/applications')
@login_required
@admin_required
def admin_applications():
    page = request.args.get('page', 1, type=int)
    applications = Application.query.order_by(Application.applied_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/applications.html', applications=applications)

@app.route('/admin/application/<int:app_id>/update_status', methods=['POST'])
@login_required
@admin_required
def admin_update_application_status(app_id):
    application = Application.query.get_or_404(app_id)
    # Admin is only allowed to set these two statuses
    allowed_statuses = {"Shortlisted", "Rejected"}
    new_status = (request.form.get('status') or '').strip()
    if new_status not in allowed_statuses:
        flash('Invalid status value.', 'danger')
        return redirect(url_for('admin_applications'))

    old_status = application.status
    application.status = new_status
    db.session.commit()
    flash('Application status updated!', 'success')

    # Notify user (in-app + optional email/push)
    if old_status != new_status:
        try:
            job_title = application.job.title if application.job else "your application"
        except Exception:
            job_title = "your application"
        create_notification(
            user_id=application.user_id,
            type="application_status",
            title="Application status updated",
            message=f"Your application for {job_title} is now {new_status}.",
            application_id=application.id,
            job_id=application.job_id,
            emit_realtime=True,
            send_email_now=True,
            push_now=True,
        )
    return redirect(url_for('admin_applications'))

@app.route('/admin/run-alert-matching', methods=['POST'])
@login_required
@admin_required
def admin_run_alert_matching():
    """Manually trigger job-alert matching (useful for testing)."""
    try:
        stats = run_job_alert_matching()
        flash(
            f"Matching completed. Alerts checked: {stats['alerts_checked']}, "
            f"Jobs scanned: {stats['jobs_scanned']}, "
            f"Notifications created: {stats['notifications_created']}.",
            'success'
        )
    except Exception as e:
        logging.exception(f"Manual matching failed: {e}")
        flash("Matching failed. Check server logs.", "danger")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    # If already logged in as admin, redirect to admin dashboard
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    # If logged in as regular user, logout first
    if current_user.is_authenticated:
        logout_user()
        flash('Please login with admin credentials.', 'info')
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.is_admin and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Welcome, Administrator!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials. Only admin users can access this portal.', 'danger')
    
    return render_template('admin/login.html')

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    
    query = User.query
    if search:
        query = query.filter(
            db.or_(
                User.username.contains(search),
                User.email.contains(search),
                User.full_name.contains(search)
            )
        )
    
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/users.html', users=users, search=search)

@app.route('/admin/user/<int:user_id>/view')
@login_required
@admin_required
def admin_view_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    user_applications = Application.query.filter_by(user_id=user_id).order_by(Application.applied_at.desc()).limit(50).all()
    return render_template('admin/view_user.html', user=user, applications=user_applications)

@app.route('/admin/user/<int:user_id>/toggle_status')
@login_required
@admin_required
def admin_toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin and user.id == current_user.id:
        flash('Cannot modify your own admin status.', 'warning')
        return redirect(url_for('admin_users'))
    # You can add an is_active field to User model if needed
    flash('User status updated.', 'success')
    return redirect(url_for('admin_users'))

def migrate_database():
    """Add new columns to existing database if they don't exist"""
    try:
        # Get table info to check existing columns
        result = db.session.execute(db.text("PRAGMA table_info(job)"))
        columns = [row[1] for row in result.fetchall()]
        
        new_columns = {
            'age_limit': 'VARCHAR(100)',
            'exam_pattern': 'TEXT',
            'official_notification_link': 'VARCHAR(500)',
            'official_website_link': 'VARCHAR(500)',
            'application_start_date': 'DATETIME',
            'application_end_date': 'DATETIME',
            'pay_scale': 'VARCHAR(200)'
        }
        
        columns_to_add = []
        for col_name, col_type in new_columns.items():
            if col_name not in columns:
                columns_to_add.append((col_name, col_type))
        
        if columns_to_add:
            print("Migrating database: Adding government job fields...")
            for col_name, col_type in columns_to_add:
                try:
                    db.session.execute(db.text(f"ALTER TABLE job ADD COLUMN {col_name} {col_type}"))
                    print(f"  ✓ Added column: {col_name}")
                except Exception as e:
                    print(f"  ✗ Error adding column {col_name}: {str(e)}")
            
            db.session.commit()
            print("✓ Database migration completed successfully!")
        else:
            print("✓ Database schema is up to date.")

        # Add last_checked_at to job_alert table if missing
        try:
            result2 = db.session.execute(db.text("PRAGMA table_info(job_alert)"))
            alert_cols = [row[1] for row in result2.fetchall()]
            if "last_checked_at" not in alert_cols:
                db.session.execute(db.text("ALTER TABLE job_alert ADD COLUMN last_checked_at DATETIME"))
                db.session.commit()
                print("  ✓ Added column: job_alert.last_checked_at")
        except Exception as e:
            db.session.rollback()
            print(f"  ✗ Error migrating job_alert: {str(e)}")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Migration error: {str(e)}")
        print("If migration fails, please delete job_portal.db and restart the application.")

def seed_sample_jobs(force=False):
    """Seed the database with sample government and private jobs"""
    # Check if jobs already exist (unless forcing)
    if not force and db.session.execute(db.select(db.func.count()).select_from(Job)).scalar() > 0:
        print("Jobs already exist. Use force=True to add more jobs.")
        return False
    
    # Get or create admin user for posted_by
    admin_user = User.query.filter_by(is_admin=True).first()
    if not admin_user:
        # Create admin if it doesn't exist
        admin_user = User(
            username='admin',
            email='admin@jobportal.com',
            password_hash=generate_password_hash('admin123'),
            full_name='Administrator',
            is_admin=True
        )
        db.session.add(admin_user)
        db.session.commit()
        print("Admin user created for seeding: username='admin', password='admin123'")
    
    admin_id = admin_user.id
    
    sample_jobs = [
        # Government Jobs
        {
            'title': 'Software Engineer - Grade A',
            'company': 'Government IT Department',
            'location': 'New Delhi',
            'job_type': 'Full-time',
            'category': 'IT',
            'job_category': 'Government',
            'description': 'We are looking for an experienced Software Engineer to join our government IT department. The candidate will work on critical government projects and systems.',
            'requirements': 'Bachelor\'s degree in Computer Science or related field. Minimum 3 years of experience in software development. Knowledge of Python, Java, and database systems.',
            'salary_min': 50000.0,
            'salary_max': 80000.0,
            'experience_required': '3-5 years',
            'deadline': datetime(2024, 12, 31),
            'age_limit': '21-35 years',
            'pay_scale': 'Level 7, Rs. 44,900 - Rs. 1,42,400',
            'exam_pattern': 'Selection Process:\n1. Written Examination (Objective Type)\n2. Technical Interview\n3. Document Verification\n\nWritten Exam: 100 questions, 2 hours duration\nTechnical Interview: 50 marks',
            'official_notification_link': 'https://www.upsc.gov.in/sites/default/files/notification/IT_Engineer_2024.pdf',
            'official_website_link': 'https://www.upsc.gov.in/recruitment/recruitment-notices',
            'application_start_date': datetime(2024, 10, 1),
            'application_end_date': datetime(2024, 12, 31)
        },
        {
            'title': 'Banking Officer - RBI',
            'company': 'Reserve Bank of India',
            'location': 'Mumbai',
            'job_type': 'Full-time',
            'category': 'Banking',
            'job_category': 'Government',
            'description': 'Join the Reserve Bank of India as a Banking Officer. Work on monetary policy, banking regulations, and financial stability initiatives.',
            'requirements': 'Graduate degree in Economics, Commerce, or related field. Strong analytical skills. Age limit: 30 years.',
            'salary_min': 60000.0,
            'salary_max': 90000.0,
            'experience_required': '0-2 years',
            'deadline': datetime(2024, 11, 30),
            'age_limit': '21-30 years',
            'pay_scale': 'Level 8, Rs. 47,600 - Rs. 1,51,100',
            'exam_pattern': 'Selection Process:\n1. Phase I: Preliminary Examination (Objective)\n2. Phase II: Main Examination (Descriptive + Objective)\n3. Interview\n\nPhase I: 100 questions, 1 hour\nPhase II: 3 papers, 3 hours each',
            'official_notification_link': 'https://www.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=4156',
            'official_website_link': 'https://www.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=4156',
            'application_start_date': datetime(2024, 9, 15),
            'application_end_date': datetime(2024, 11, 30)
        },
        {
            'title': 'Assistant Professor - Computer Science',
            'company': 'Government Engineering College',
            'location': 'Bangalore',
            'job_type': 'Full-time',
            'category': 'Education',
            'job_category': 'Government',
            'description': 'Assistant Professor position in Computer Science department. Teach undergraduate and graduate courses, conduct research.',
            'requirements': 'Ph.D. in Computer Science or related field. Minimum 2 years of teaching experience. Published research papers preferred.',
            'salary_min': 70000.0,
            'salary_max': 100000.0,
            'experience_required': '2-5 years',
            'deadline': datetime(2024, 12, 15),
            'age_limit': 'No upper age limit',
            'pay_scale': 'Level 10, Rs. 57,700 - Rs. 1,82,400',
            'exam_pattern': 'Selection Process:\n1. Written Test (Subject Knowledge)\n2. Presentation on Research Work\n3. Interview\n\nWritten Test: 2 hours, 100 marks\nPresentation: 20 minutes\nInterview: 30 minutes',
            'official_notification_link': 'https://www.ugc.gov.in/pdfnews/4273085_Assistant-Professor-Recruitment-2024.pdf',
            'official_website_link': 'https://www.ugc.gov.in/recruitment',
            'application_start_date': datetime(2024, 10, 1),
            'application_end_date': datetime(2024, 12, 15)
        },
        {
            'title': 'Civil Engineer - PWD',
            'company': 'Public Works Department',
            'location': 'Chennai',
            'job_type': 'Full-time',
            'category': 'Engineering',
            'job_category': 'Government',
            'description': 'Civil Engineer position in Public Works Department. Work on infrastructure projects including roads, bridges, and public buildings.',
            'requirements': 'B.E./B.Tech in Civil Engineering. Minimum 2 years of experience in infrastructure projects. Knowledge of AutoCAD and project management.',
            'salary_min': 45000.0,
            'salary_max': 70000.0,
            'experience_required': '2-4 years',
            'deadline': datetime(2024, 11, 25),
            'age_limit': '18-35 years',
            'pay_scale': 'Level 6, Rs. 35,400 - Rs. 1,12,400',
            'exam_pattern': 'Selection Process:\n1. Written Examination (Technical)\n2. Document Verification\n3. Interview\n\nWritten Exam: 2 papers, 3 hours each\nPaper I: General Engineering\nPaper II: Civil Engineering',
            'official_notification_link': 'https://www.tnpsc.gov.in/notification/civil-engineer-2024.pdf',
            'official_website_link': 'https://www.tnpsc.gov.in/apply-online',
            'application_start_date': datetime(2024, 9, 1),
            'application_end_date': datetime(2024, 11, 25)
        },
        {
            'title': 'Medical Officer - Health Department',
            'company': 'State Health Department',
            'location': 'Hyderabad',
            'job_type': 'Full-time',
            'category': 'Healthcare',
            'job_category': 'Government',
            'description': 'Medical Officer position in State Health Department. Provide medical services in government hospitals and health centers.',
            'requirements': 'MBBS degree with valid medical license. Minimum 1 year of experience. Willingness to work in rural areas.',
            'salary_min': 80000.0,
            'salary_max': 120000.0,
            'experience_required': '1-3 years',
            'deadline': datetime(2024, 12, 10),
            'age_limit': '21-40 years',
            'pay_scale': 'Level 9, Rs. 53,100 - Rs. 1,67,800',
            'exam_pattern': 'Selection Process:\n1. Written Examination (Medical Knowledge)\n2. Clinical Examination\n3. Interview\n\nWritten Exam: 200 questions, 3 hours\nClinical Exam: Practical assessment',
            'official_notification_link': 'https://www.mohfw.gov.in/pdf/Medical-Officer-Recruitment-2024.pdf',
            'official_website_link': 'https://www.mohfw.gov.in/recruitment',
            'application_start_date': datetime(2024, 10, 15),
            'application_end_date': datetime(2024, 12, 10)
        },
        {
            'title': 'Police Sub-Inspector',
            'company': 'State Police Department',
            'location': 'Pune',
            'job_type': 'Full-time',
            'category': 'Law Enforcement',
            'job_category': 'Government',
            'description': 'Join the police force as Sub-Inspector. Maintain law and order, investigate cases, and serve the community.',
            'requirements': 'Graduate degree from recognized university. Physical fitness test required. Age limit: 21-28 years.',
            'salary_min': 40000.0,
            'salary_max': 60000.0,
            'experience_required': '0-1 years',
            'deadline': datetime(2024, 11, 20),
            'age_limit': '21-28 years',
            'pay_scale': 'Level 5, Rs. 29,200 - Rs. 92,300',
            'exam_pattern': 'Selection Process:\n1. Written Examination\n2. Physical Efficiency Test (PET)\n3. Physical Standard Test (PST)\n4. Medical Examination\n5. Interview\n\nWritten Exam: 2 papers, 2 hours each\nPET: Running, Long Jump, High Jump\nPST: Height, Chest, Weight measurement',
            'official_notification_link': 'https://www.mahapolice.gov.in/recruitment/PSI-Notification-2024.pdf',
            'official_website_link': 'https://www.mahapolice.gov.in/recruitment/apply',
            'application_start_date': datetime(2024, 9, 1),
            'application_end_date': datetime(2024, 11, 20)
        },
        # Private Jobs
        {
            'title': 'Senior Software Developer',
            'company': 'Tech Solutions Pvt Ltd',
            'location': 'Bangalore',
            'job_type': 'Full-time',
            'category': 'IT',
            'job_category': 'Private',
            'description': 'We are seeking a Senior Software Developer to join our dynamic team. Work on cutting-edge web applications using modern technologies.',
            'requirements': 'Bachelor\'s degree in Computer Science. 5+ years of experience in full-stack development. Proficiency in Python, JavaScript, React, and Node.js.',
            'salary_min': 120000.0,
            'salary_max': 180000.0,
            'experience_required': '5-8 years',
            'deadline': datetime(2024, 12, 20)
        },
        {
            'title': 'Marketing Manager',
            'company': 'Global Marketing Agency',
            'location': 'Mumbai',
            'job_type': 'Full-time',
            'category': 'Marketing',
            'job_category': 'Private',
            'description': 'Lead our marketing team and develop strategies to grow brand awareness and drive sales. Manage digital marketing campaigns and team.',
            'requirements': 'MBA in Marketing or related field. 4+ years of marketing experience. Strong analytical and communication skills.',
            'salary_min': 80000.0,
            'salary_max': 120000.0,
            'experience_required': '4-6 years',
            'deadline': datetime(2024, 12, 5)
        },
        {
            'title': 'Data Scientist',
            'company': 'AI Innovations Inc',
            'location': 'Hyderabad',
            'job_type': 'Full-time',
            'category': 'IT',
            'job_category': 'Private',
            'description': 'Join our AI team as a Data Scientist. Work on machine learning models, data analysis, and predictive analytics projects.',
            'requirements': 'Master\'s or Ph.D. in Data Science, Statistics, or related field. Experience with Python, TensorFlow, and SQL. Strong mathematical background.',
            'salary_min': 150000.0,
            'salary_max': 250000.0,
            'experience_required': '3-6 years',
            'deadline': datetime(2024, 12, 18)
        },
        {
            'title': 'HR Manager',
            'company': 'Corporate Solutions Ltd',
            'location': 'Delhi',
            'job_type': 'Full-time',
            'category': 'Human Resources',
            'job_category': 'Private',
            'description': 'Manage HR operations including recruitment, employee relations, performance management, and policy implementation.',
            'requirements': 'MBA in HR or related field. 5+ years of HR experience. Strong interpersonal and organizational skills.',
            'salary_min': 70000.0,
            'salary_max': 100000.0,
            'experience_required': '5-7 years',
            'deadline': datetime(2024, 12, 12)
        },
        {
            'title': 'Financial Analyst',
            'company': 'Investment Bank',
            'location': 'Mumbai',
            'job_type': 'Full-time',
            'category': 'Finance',
            'job_category': 'Private',
            'description': 'Analyze financial data, prepare reports, and provide investment recommendations. Work with clients on portfolio management.',
            'requirements': 'CA, CFA, or MBA in Finance. 3+ years of financial analysis experience. Strong Excel and financial modeling skills.',
            'salary_min': 100000.0,
            'salary_max': 150000.0,
            'experience_required': '3-5 years',
            'deadline': datetime(2024, 12, 8)
        },
        {
            'title': 'Product Manager',
            'company': 'E-Commerce Platform',
            'location': 'Bangalore',
            'job_type': 'Full-time',
            'category': 'Product Management',
            'job_category': 'Private',
            'description': 'Lead product development from conception to launch. Work with engineering, design, and business teams to deliver great products.',
            'requirements': 'Bachelor\'s degree in Engineering or Business. 4+ years of product management experience. Strong technical and business acumen.',
            'salary_min': 130000.0,
            'salary_max': 200000.0,
            'experience_required': '4-7 years',
            'deadline': datetime(2024, 12, 25)
        },
        {
            'title': 'Graphic Designer',
            'company': 'Creative Design Studio',
            'location': 'Pune',
            'job_type': 'Full-time',
            'category': 'Design',
            'job_category': 'Private',
            'description': 'Create visual concepts and designs for various marketing materials, websites, and branding projects.',
            'requirements': 'Bachelor\'s degree in Graphic Design or related field. Proficiency in Adobe Creative Suite. Strong portfolio required.',
            'salary_min': 40000.0,
            'salary_max': 60000.0,
            'experience_required': '2-4 years',
            'deadline': datetime(2024, 12, 15)
        },
        {
            'title': 'Sales Executive',
            'company': 'Retail Corporation',
            'location': 'Chennai',
            'job_type': 'Full-time',
            'category': 'Sales',
            'job_category': 'Private',
            'description': 'Drive sales growth by building relationships with clients, identifying opportunities, and closing deals.',
            'requirements': 'Graduate degree. 2+ years of sales experience. Excellent communication and negotiation skills.',
            'salary_min': 30000.0,
            'salary_max': 50000.0,
            'experience_required': '2-4 years',
            'deadline': datetime(2024, 12, 10)
        }
    ]
    
    for job_data in sample_jobs:
        job = Job(
            title=job_data['title'],
            company=job_data['company'],
            location=job_data['location'],
            job_type=job_data['job_type'],
            category=job_data['category'],
            job_category=job_data['job_category'],
            description=job_data['description'],
            requirements=job_data['requirements'],
            salary_min=job_data['salary_min'],
            salary_max=job_data['salary_max'],
            experience_required=job_data['experience_required'],
            posted_by=admin_id,
            is_active=True,
            deadline=job_data['deadline']
        )
        
        # Add government job specific fields if present
        if job_data['job_category'] == 'Government' and 'age_limit' in job_data:
            job.age_limit = job_data.get('age_limit')
            job.exam_pattern = job_data.get('exam_pattern')
            job.official_notification_link = job_data.get('official_notification_link')
            job.official_website_link = job_data.get('official_website_link')
            job.pay_scale = job_data.get('pay_scale')
            job.application_start_date = job_data.get('application_start_date')
            job.application_end_date = job_data.get('application_end_date')
        
        db.session.add(job)
    
    try:
        db.session.commit()
        print(f"✓ Successfully seeded {len(sample_jobs)} sample jobs (Government and Private)")
        return True
    except Exception as e:
        db.session.rollback()
        print(f"✗ Error seeding jobs: {str(e)}")
        return False

@app.route('/admin/seed-jobs', methods=['POST'])
@login_required
@admin_required
def admin_seed_jobs():
    """Admin route to manually seed sample jobs"""
    result = seed_sample_jobs(force=True)
    if result:
        flash(f'Successfully added sample jobs!', 'success')
    else:
        flash('Error adding sample jobs. Check console for details.', 'danger')
    return redirect(url_for('admin_jobs'))

@app.route('/admin/update-govt-links', methods=['POST'])
@login_required
@admin_required
def admin_update_govt_links():
    """Update official links for existing government jobs"""
    try:
        govt_jobs = Job.query.filter_by(job_category='Government').all()
        updated_count = 0
        
        # Link mappings based on company/department (with partial matching)
        link_mappings = {
            'Government IT Department': {
                'notification': 'https://www.upsc.gov.in/sites/default/files/notification/IT_Engineer_2024.pdf',
                'website': 'https://www.upsc.gov.in/recruitment/recruitment-notices'
            },
            'Reserve Bank of India': {
                'notification': 'https://www.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=4156',
                'website': 'https://www.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=4156'
            },
            'Government Engineering College': {
                'notification': 'https://www.ugc.gov.in/pdfnews/4273085_Assistant-Professor-Recruitment-2024.pdf',
                'website': 'https://www.ugc.gov.in/recruitment'
            },
            'Public Works Department': {
                'notification': 'https://www.tnpsc.gov.in/notification/civil-engineer-2024.pdf',
                'website': 'https://www.tnpsc.gov.in/apply-online'
            },
            'State Health Department': {
                'notification': 'https://www.mohfw.gov.in/pdf/Medical-Officer-Recruitment-2024.pdf',
                'website': 'https://www.mohfw.gov.in/recruitment'
            },
            'State Police Department': {
                'notification': 'https://www.mahapolice.gov.in/recruitment/PSI-Notification-2024.pdf',
                'website': 'https://www.mahapolice.gov.in/recruitment/apply'
            }
        }
        
        # Default links for unmatched jobs
        default_links = {
            'notification': 'https://www.upsc.gov.in/recruitment/recruitment-notices',
            'website': 'https://www.upsc.gov.in/recruitment/recruitment-notices'
        }
        
        for job in govt_jobs:
            # Try exact match first
            if job.company in link_mappings:
                job.official_notification_link = link_mappings[job.company]['notification']
                job.official_website_link = link_mappings[job.company]['website']
                updated_count += 1
            # Try partial matching for variations
            else:
                matched = False
                company_lower = job.company.lower()
                for key, links in link_mappings.items():
                    if any(word in company_lower for word in key.lower().split() if len(word) > 3):
                        job.official_notification_link = links['notification']
                        job.official_website_link = links['website']
                        updated_count += 1
                        matched = True
                        break
                
                # If no match found, use default links
                if not matched and not job.official_website_link:
                    job.official_notification_link = default_links['notification']
                    job.official_website_link = default_links['website']
                    updated_count += 1
        
        db.session.commit()
        flash(f'Successfully updated links for {updated_count} government jobs!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating links: {str(e)}', 'danger')
    
    return redirect(url_for('admin_jobs'))

def auto_update_govt_links():
    """Automatically update government job links if they're missing"""
    try:
        govt_jobs = Job.query.filter_by(job_category='Government').all()
        updated_count = 0
        
        # Link mappings based on company/department
        link_mappings = {
            'Government IT Department': {
                'notification': 'https://www.upsc.gov.in/sites/default/files/notification/IT_Engineer_2024.pdf',
                'website': 'https://www.upsc.gov.in/recruitment/recruitment-notices'
            },
            'Reserve Bank of India': {
                'notification': 'https://www.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=4156',
                'website': 'https://www.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=4156'
            },
            'Government Engineering College': {
                'notification': 'https://www.ugc.gov.in/pdfnews/4273085_Assistant-Professor-Recruitment-2024.pdf',
                'website': 'https://www.ugc.gov.in/recruitment'
            },
            'Public Works Department': {
                'notification': 'https://www.tnpsc.gov.in/notification/civil-engineer-2024.pdf',
                'website': 'https://www.tnpsc.gov.in/apply-online'
            },
            'State Health Department': {
                'notification': 'https://www.mohfw.gov.in/pdf/Medical-Officer-Recruitment-2024.pdf',
                'website': 'https://www.mohfw.gov.in/recruitment'
            },
            'State Police Department': {
                'notification': 'https://www.mahapolice.gov.in/recruitment/PSI-Notification-2024.pdf',
                'website': 'https://www.mahapolice.gov.in/recruitment/apply'
            }
        }
        
        # Default links for unmatched jobs
        default_links = {
            'notification': 'https://www.upsc.gov.in/recruitment/recruitment-notices',
            'website': 'https://www.upsc.gov.in/recruitment/recruitment-notices'
        }
        
        for job in govt_jobs:
            # Only update if link is missing
            if not job.official_website_link:
                # Try exact match first
                if job.company in link_mappings:
                    job.official_notification_link = link_mappings[job.company]['notification']
                    job.official_website_link = link_mappings[job.company]['website']
                    updated_count += 1
                # Try partial matching for variations
                else:
                    matched = False
                    company_lower = job.company.lower()
                    for key, links in link_mappings.items():
                        if any(word in company_lower for word in key.lower().split() if len(word) > 3):
                            job.official_notification_link = links['notification']
                            job.official_website_link = links['website']
                            updated_count += 1
                            matched = True
                            break
                    
                    # If no match found, use default links
                    if not matched:
                        job.official_notification_link = default_links['notification']
                        job.official_website_link = default_links['website']
                        updated_count += 1
        
        if updated_count > 0:
            db.session.commit()
            print(f"✓ Auto-updated links for {updated_count} government jobs")
    except Exception as e:
        db.session.rollback()
        print(f"✗ Error auto-updating links: {str(e)}")

with app.app_context():
        db.create_all()
        
        # Migrate database to add new columns
        migrate_database()
        
        # Create admin user if not exists
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin = User(
                username='admin',
                email='admin@jobportal.com',
                password_hash=generate_password_hash('admin123'),
                full_name='Administrator',
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print("✓ Admin user created: username='admin', password='admin123'")
        
        # Seed sample jobs (only if database is empty)
        seed_sample_jobs(force=False)
        
        # Auto-update government job links if missing
        auto_update_govt_links()

        # Start cron-like scheduler (runs job-alert matching every N minutes)
        # Only start once when using the Flask reloader
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
            start_scheduler()
if __name__ == '__main__':
    
    
    if socketio is not None:
        socketio.run(app, debug=True)
    else:
        app.run(debug=True)

