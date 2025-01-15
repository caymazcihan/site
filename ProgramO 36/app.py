from sqlite3 import IntegrityError
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from collections import defaultdict
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import re
import copy
import random
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "default_secret_key")

# Veritabanı Konfigürasyonu
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ders_dagitim.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# Kullanıcılar Tablosu
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    school_name = db.Column(db.String(120))
    school_email = db.Column(db.String(120))
    school_principal = db.Column(db.String(120))
    role = db.Column(db.String(20), nullable=False, default="user")

    teachers = db.relationship("Teacher", backref="user", lazy=True)
    classes = db.relationship("Class", backref="user", lazy=True)
    courses = db.relationship("Course", backref="user", lazy=True)
    assignments = db.relationship("TeacherCourseAssignment", backref="user", lazy=True)
    schedules = db.relationship("Schedule", backref="user", lazy=True)

    def __repr__(self):
        return f"<User {self.username}>"


class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    surname = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=True)
    branch = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    schedules = db.relationship(
        "TeacherSchedule", backref="teacher", cascade="all, delete-orphan", lazy=True
    )


class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(20), nullable=False)
    weekly_hours = db.Column(db.Integer, nullable=False)
    distribution_format = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class TeacherCourseAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    course = db.relationship("Course", backref="assignments", lazy=True)
    teacher = db.relationship("Teacher", backref="assignments", lazy=True)
    class_ = db.relationship("Class", backref="assignments", lazy=True)


class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), nullable=False)
    hour = db.Column(db.Integer, nullable=False)
    is_open = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    def __repr__(self):
        return f"<Schedule {self.day} {self.hour}>"


class TeacherSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(20), nullable=False)
    hour = db.Column(db.Integer, nullable=False)
    is_open = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    user = db.relationship("User", backref=db.backref("teacher_schedules", lazy=True))
    teacher_ref = db.relationship(
        "Teacher", back_populates="schedules", overlaps="teacher"
    )


class CourseSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), nullable=False)
    hour = db.Column(db.Integer, nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=True)
    class_id = db.Column(db.Integer, db.ForeignKey("class.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    course = db.relationship("Course", backref="course_schedules", lazy=True)
    teacher = db.relationship("Teacher", backref="course_schedules", lazy=True)
    class_ = db.relationship("Class", backref="course_schedules", lazy=True)
    user = db.relationship("User", backref="course_schedules", lazy=True)


with app.app_context():
    db.create_all()
    print("Veritabanı oluşturuldu!")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


# Yardımcı Fonksiyonlar
def format_name(name):
    """Adı uygun formata getirir (boşlukları temizler, baş harflerini büyük yapar)."""
    return name.strip().title()


def validate_email(email):
    """E-posta formatını kontrol eder."""
    if not email:
        return None
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return False  # Geçersiz format
    return email.lower()


def validate_course_format(format_str, weekly_hours):
    if not all(c.isdigit() or c == "+" for c in format_str):
        return (
            "Yerleştirme biçimi sadece rakamlar ve '+' işaretinden oluşmalıdır!",
            False,
        )

    distribution_numbers = [int(num) for num in format_str.split("+") if num.isdigit()]
    if sum(distribution_numbers) != weekly_hours:
        return (
            "Haftalık ders saati ile yerleştirme biçimindeki sayıların toplamı eşit olmalıdır!",
            False,
        )

    return True, None


# ROUTES
@app.route("/")
@login_required
def home():
    return render_template("index.html", page_title="Anasayfa")


@app.route("/okul-bilgileri", methods=["GET", "POST"])
@login_required
def okul_bilgileri():
    current_user = User.query.filter_by(id=session["user_id"]).first()
    schedules_from_db = Schedule.query.filter_by(user_id=current_user.id).all()
    schedule = {day: {hour: False for hour in HOURS} for day in DAYS}
    for entry in schedules_from_db:
        schedule[entry.day][entry.hour] = entry.is_open

    if request.method == "POST":
        school_name = request.form.get("school_name")
        school_email = request.form.get("school_email")
        school_principal = request.form.get("school_principal")
        current_user.school_name = school_name
        current_user.school_email = school_email
        current_user.school_principal = school_principal

        for day in DAYS:
            for hour in HOURS:
                checkbox_id = f"{day}-{hour}"
                is_checked = checkbox_id in request.form
                existing_entry = Schedule.query.filter_by(
                    day=day, hour=hour, user_id=current_user.id
                ).first()

                if existing_entry:
                    existing_entry.is_open = is_checked
                else:
                    new_entry = Schedule(
                        day=day, hour=hour, is_open=is_checked, user_id=current_user.id
                    )
                    db.session.add(new_entry)
        db.session.commit()
        flash("Okul bilgileri güncellendi.", "success")
        return redirect(url_for("okul_bilgileri"))
    return render_template(
        "okul_bilgileri.html",
        schedule=schedule,
        school_name=current_user.school_name,
        school_email=current_user.school_email,
        school_principal=current_user.school_principal,
        days=DAYS,
        hours=HOURS,
    )


@app.route("/ogretmen-programi", methods=["GET", "POST"])
@login_required
def ogretmen_programi():
    current_user = User.query.filter_by(id=session["user_id"]).first()
    teachers = (
        Teacher.query.filter_by(user_id=current_user.id).order_by(Teacher.name).all()
    )
    school_schedules = Schedule.query.filter_by(
        user_id=current_user.id, is_open=True
    ).all()
    open_hours_by_day = create_open_day_hour_set(school_schedules)

    max_hours = (
        max(len(hours) for hours in open_hours_by_day.values())
        if open_hours_by_day
        else 0
    )

    selected_teacher_id = request.args.get("teacher_id")
    selected_teacher = None
    teacher_schedule_data = {
        day: {hour: False for hour in hours} for day, hours in open_hours_by_day.items()
    }

    if selected_teacher_id:
        selected_teacher = Teacher.query.get_or_404(selected_teacher_id)

        # Öğretmenin programını al
        teacher_schedule = TeacherSchedule.query.filter_by(
            teacher_id=selected_teacher_id
        ).all()
        for entry in teacher_schedule:
            if (
                entry.day in open_hours_by_day
                and entry.hour in open_hours_by_day[entry.day]
            ):
                teacher_schedule_data[entry.day][entry.hour] = entry.is_open

    if request.method == "POST":
        selected_teacher_id = request.form.get("teacher_id")
        selected_teacher = Teacher.query.get_or_404(selected_teacher_id)

        # Önce mevcut kayıtları temizle
        TeacherSchedule.query.filter(
            TeacherSchedule.teacher_id == selected_teacher_id,
            TeacherSchedule.day.in_(open_hours_by_day.keys()),
            TeacherSchedule.hour.in_(
                hour for sublist in open_hours_by_day.values() for hour in sublist
            ),
        ).delete(synchronize_session=False)

        # Sonra yeni kayıtları ekle
        for day, hours in open_hours_by_day.items():
            for hour in hours:
                checkbox_id = f"{day}-{hour}"
                is_checked = checkbox_id in request.form
                if is_checked:
                    new_entry = TeacherSchedule(
                        day=day,
                        hour=hour,
                        is_open=True,
                        teacher_id=selected_teacher_id,
                        user_id=current_user.id,
                    )
                    db.session.add(new_entry)

        db.session.commit()
        flash("Öğretmen programı başarıyla kaydedildi.", "success")
        return redirect(url_for("ogretmen_programi", teacher_id=selected_teacher_id))

    return render_template(
        "ogretmen_programi.html",
        schedule={
            day: {hour: True for hour in hours}
            for day, hours in open_hours_by_day.items()
        },
        teachers=teachers,
        selected_teacher_id=selected_teacher_id,
        selected_teacher=selected_teacher,
        teacher_schedule_data=teacher_schedule_data,
        open_hours_by_day=open_hours_by_day,
        max_hours=max_hours,
    )


# Okul Programını Öğretmenlere Ata
@app.route("/assign-school-schedule-to-teachers", methods=["POST"])
@login_required
def assign_school_schedule_to_teachers():
    current_user = User.query.filter_by(username=session["username"]).first()
    school_schedule = Schedule.query.filter_by(user_id=current_user.id).all()

    if not school_schedule:
        flash("Okul programı bulunamadı.", "danger")
        return redirect(url_for("ogretmen_programi"))

    teachers = Teacher.query.filter_by(user_id=current_user.id).all()

    if not teachers:
        flash("Öğretmen bulunamadı.", "danger")
        return redirect(url_for("ogretmen_programi"))
    for teacher in teachers:
        TeacherSchedule.query.filter(
            TeacherSchedule.teacher_id == teacher.id,
            TeacherSchedule.day.in_(DAYS),
            TeacherSchedule.hour.in_(HOURS),
        ).delete(synchronize_session=False)
        for entry in school_schedule:
            new_schedule = TeacherSchedule(
                day=entry.day,
                hour=entry.hour,
                is_open=entry.is_open,
                teacher_id=teacher.id,
                user_id=current_user.id,
            )
            db.session.add(new_schedule)
    db.session.commit()
    flash("Okul programı öğretmenlere başarıyla atandı.", "success")
    return redirect(url_for("ogretmen_programi"))


# Öğretmen Ekle
@app.route("/ogretmen-ekle", methods=["GET", "POST"])
@login_required
def add_teacher():
    current_user = User.query.filter_by(username=session["username"]).first()

    if request.method == "POST":

        name = request.form.get("ad").strip()
        surname = request.form.get("soyad").strip()
        email = request.form.get("email").strip() if request.form.get("email") else None
        branch = request.form.get("brans").strip()

        # E-posta format kontrolü
        if email and not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash("Geçersiz e-posta adresi! Lütfen doğru formatta giriniz.", "danger")
            return redirect(url_for("add_teacher"))

        new_teacher = Teacher(
            name=name.lower().title(),
            surname=surname.lower().title(),
            email=email.lower() if email else None,
            branch=branch.lower().title(),
            user_id=current_user.id,
        )
        db.session.add(new_teacher)
        db.session.commit()

        flash(f"{name} {surname} başarıyla eklendi!", "success")
        return redirect(url_for("add_teacher"))

    teachers = (
        Teacher.query.filter_by(user_id=current_user.id)
        .order_by(Teacher.name, Teacher.surname)
        .all()
    )  # Sadece kullanıcının öğretmenlerini listele
    return render_template(
        "add_teacher.html",
        teachers=teachers,
        teacher_to_edit=None,
        page_title="Öğretmen Ekle",
    )


# Öğretmen Düzenle
@app.route("/ogretmen-duzenle/<int:teacher_id>", methods=["GET", "POST"])
@login_required
def edit_teacher(teacher_id):
    current_user = User.query.filter_by(username=session["username"]).first()
    teacher_to_edit = Teacher.query.filter_by(
        id=teacher_id, user_id=current_user.id
    ).first_or_404()
    if teacher_to_edit.email == None:
        teacher_to_edit.email = ""
    if request.method == "POST":
        # Küçük harfe çevir, sonra title() uygula
        teacher_to_edit.name = request.form.get("ad").lower().title()
        # Küçük harfe çevir, sonra title() uygula
        teacher_to_edit.surname = request.form.get("soyad").lower().title()
        teacher_to_edit.email = (
            request.form.get("email").lower() if request.form.get("email") else ""
        )
        teacher_to_edit.branch = request.form.get("brans").lower().title()

        # E-posta format kontrolü
        if teacher_to_edit.email and not re.match(
            r"[^@]+@[^@]+\.[^@]+", teacher_to_edit.email
        ):
            flash("Geçersiz e-posta adresi! Lütfen doğru formatta giriniz.", "danger")
            return redirect(url_for("edit_teacher", teacher_id=teacher_id))

        db.session.commit()
        flash(
            f"{teacher_to_edit.name} {teacher_to_edit.surname} başarıyla güncellendi!",
            "success",
        )
        return redirect(url_for("add_teacher"))

    teachers = (
        Teacher.query.filter_by(user_id=current_user.id)
        .order_by(Teacher.name, Teacher.surname)
        .all()
    )
    return render_template(
        "add_teacher.html",
        teachers=teachers,
        teacher_to_edit=teacher_to_edit,
        page_title="Öğretmen Düzenle",
    )


# Öğretmen Silme
@app.route("/ogretmen-sil/<int:teacher_id>", methods=["GET"])
@login_required
def delete_teacher(teacher_id):
    current_user = User.query.filter_by(username=session["username"]).first()
    teacher = Teacher.query.filter_by(
        id=teacher_id, user_id=current_user.id
    ).first_or_404()

    assignments = TeacherCourseAssignment.query.filter_by(
        teacher_id=teacher.id, user_id=current_user.id
    ).all()
    for assignment in assignments:
        db.session.delete(assignment)

    db.session.delete(teacher)
    db.session.commit()

    flash(f"{teacher.name} başarıyla silindi!", "success")
    return redirect(url_for("add_teacher"))


# Sınıf Ekle
@app.route("/sinif-ekle", methods=["GET", "POST"])
@login_required
def add_class():
    current_user = User.query.filter_by(username=session["username"]).first()

    if request.method == "POST":
        class_name = request.form.get("sinif_adi")

        # Sınıf adı boşluk kontrolü
        if not class_name:
            flash("Sınıf adı boş bırakılamaz!", "danger")
            return redirect(url_for("add_class"))

        # Sadece harf ve sayı kontrolü (Python tarafında)
        if not class_name.isalnum():
            flash("Sınıf adı sadece harf ve rakamlardan oluşmalıdır!", "danger")
            return redirect(url_for("add_class"))

        # Büyük harfe çevirme
        class_name = class_name.upper()

        new_class = Class(
            class_name=class_name, user_id=current_user.id  # Kullanıcı ID'sini ekle
        )
        db.session.add(new_class)
        db.session.commit()
        flash(f"{class_name} başarıyla eklendi!", "success")
        return redirect(url_for("add_class"))

    classes = (
        Class.query.filter_by(user_id=current_user.id).order_by(Class.class_name).all()
    )  # Sadece kullanıcının sınıflarını listele
    return render_template(
        "add_class.html", classes=classes, class_to_edit=None, page_title="Sınıf Ekle"
    )


# Sınıf Düzenle
@app.route("/sinif-duzenle/<int:class_id>", methods=["GET", "POST"])
@login_required
def edit_class(class_id):
    current_user = User.query.filter_by(username=session["username"]).first()
    class_to_edit = Class.query.filter_by(
        id=class_id, user_id=current_user.id
    ).first_or_404()

    if request.method == "POST":
        new_name = request.form.get("sinif_adi")
        if not new_name:
            flash("Sınıf adı boş bırakılamaz!", "danger")
            return redirect(url_for("edit_class", class_id=class_id))

        class_to_edit.class_name = new_name
        db.session.commit()
        flash(f"Sınıf başarıyla güncellendi: {new_name}", "success")
        return redirect(url_for("add_class"))

    classes = (
        Class.query.filter_by(user_id=current_user.id).order_by(Class.class_name).all()
    )
    return render_template(
        "add_class.html",
        classes=classes,
        class_to_edit=class_to_edit,
        page_title="Sınıf Düzenle",
    )


# Sınıf Sil
@app.route("/sinif-sil/<int:class_id>", methods=["GET"])
@login_required
def delete_class(class_id):
    current_user = User.query.filter_by(username=session["username"]).first()
    class_to_delete = Class.query.filter_by(
        id=class_id, user_id=current_user.id
    ).first_or_404()

    assignments = TeacherCourseAssignment.query.filter_by(
        class_id=class_id, user_id=current_user.id
    ).all()
    for assignment in assignments:
        db.session.delete(assignment)

    db.session.delete(class_to_delete)
    db.session.commit()
    flash(f"{class_to_delete.class_name} başarıyla silindi!", "success")
    return redirect(url_for("add_class"))


# Ders Ekle
@app.route("/ders-ekle", methods=["GET", "POST"])
@login_required
def add_course():
    current_user = User.query.filter_by(username=session["username"]).first()

    if request.method == "POST":
        course_name = request.form.get("ders_adi").lower().title()
        short_name = request.form.get("ders_kisa_adi").upper()
        weekly_hours = int(request.form.get("haftalik_ders_sayisi"))  # Integer'a çevir
        distribution_format = request.form.get("yerlestirme_bicimi")

        # Yerleştirme biçimi kontrolü (sadece sayı ve + içermeli)
        if not all(c.isdigit() or c == "+" for c in distribution_format):
            flash(
                "Yerleştirme biçimi sadece rakamlar ve '+' işaretinden oluşmalıdır!",
                "danger",
            )
            return redirect(url_for("add_course"))

        # Haftalık ders saati ve yerleştirme biçimi toplam kontrolü
        distribution_numbers = [
            int(num) for num in distribution_format.split("+") if num.isdigit()
        ]
        if sum(distribution_numbers) != weekly_hours:
            flash(
                "Haftalık ders saati ile yerleştirme biçimindeki sayıların toplamı eşit olmalıdır!",
                "danger",
            )
            return redirect(url_for("add_course"))

        new_course = Course(
            course_name=course_name,
            short_name=short_name,
            weekly_hours=weekly_hours,
            distribution_format=distribution_format,
            user_id=current_user.id,
        )
        db.session.add(new_course)
        db.session.commit()
        flash(f"{course_name} başarıyla eklendi!", "success")
        return redirect(url_for("add_course"))

    courses = (
        Course.query.filter_by(user_id=current_user.id)
        .order_by(Course.course_name)
        .all()
    )  # Sadece kullanıcının derslerini listele
    return render_template(
        "add_course.html", courses=courses, course_to_edit=None, page_title="Ders Ekle"
    )


# Ders Düzenle
@app.route("/ders-duzenle/<int:course_id>", methods=["GET", "POST"])
@login_required
def edit_course(course_id):
    current_user = User.query.filter_by(username=session["username"]).first()
    course_to_edit = Course.query.filter_by(
        id=course_id, user_id=current_user.id
    ).first_or_404()

    if request.method == "POST":
        course_to_edit.course_name = request.form.get("ders_adi").lower().title()
        course_to_edit.short_name = request.form.get("ders_kisa_adi").upper()
        course_to_edit.weekly_hours = int(request.form.get("haftalik_ders_sayisi"))
        course_to_edit.distribution_format = request.form.get("yerlestirme_bicimi")

        # Yerleştirme biçimi kontrolü (sadece sayı ve + içermeli)
        if not all(c.isdigit() or c == "+" for c in course_to_edit.distribution_format):
            flash(
                "Yerleştirme biçimi sadece rakamlar ve '+' işaretinden oluşmalıdır!",
                "danger",
            )
            return redirect(url_for("edit_course", course_id=course_id))

        # Haftalık ders saati ve yerleştirme biçimi toplam kontrolü
        distribution_numbers = [
            int(num)
            for num in course_to_edit.distribution_format.split("+")
            if num.isdigit()
        ]
        if sum(distribution_numbers) != course_to_edit.weekly_hours:
            flash(
                "Haftalık ders saati ile yerleştirme biçimindeki sayıların toplamı eşit olmalıdır!",
                "danger",
            )
            return redirect(url_for("edit_course", course_id=course_id))

        db.session.commit()
        flash(f"{course_to_edit.course_name} başarıyla güncellendi!", "success")
        return redirect(url_for("add_course"))

    courses = (
        Course.query.filter_by(user_id=current_user.id)
        .order_by(Course.course_name)
        .all()
    )
    return render_template(
        "add_course.html",
        courses=courses,
        course_to_edit=course_to_edit,
        page_title="Ders Düzenle",
    )


# Ders Silme
@app.route("/ders-sil/<int:course_id>", methods=["GET"])
@login_required
def delete_course(course_id):
    current_user = User.query.filter_by(username=session["username"]).first()
    course = Course.query.filter_by(
        id=course_id, user_id=current_user.id
    ).first_or_404()

    assignments = TeacherCourseAssignment.query.filter_by(
        course_id=course.id, user_id=current_user.id
    ).all()
    for assignment in assignments:
        db.session.delete(assignment)

    db.session.delete(course)
    db.session.commit()

    flash(f"{course.course_name} başarıyla silindi!", "success")
    return redirect(url_for("add_course"))


# Ders Atama
@app.route("/ders-atama", methods=["GET", "POST"])
@login_required
def assign_course():
    current_user = User.query.filter_by(username=session["username"]).first()

    # Seçili değerleri al (GET isteği için)
    filter_class = request.args.get("sinif_secimi")
    filter_teacher = request.args.get("ogretmen_secimi")
    filter_course = request.args.get("ders_secimi")

    query = TeacherCourseAssignment.query.filter_by(user_id=current_user.id)

    if filter_class:
        query = query.filter_by(class_id=filter_class)
    if filter_teacher:
        query = query.filter_by(teacher_id=filter_teacher)
    if filter_course:
        query = query.filter_by(course_id=filter_course)

    # Programları öğretmen ismine göre sırala
    programlar = query.join(Teacher).order_by(Teacher.name, Teacher.surname).all()

    # Verileri alfabetik olarak sırala
    courses = (
        Course.query.filter_by(user_id=current_user.id)
        .order_by(Course.course_name)
        .all()
    )
    classes = (
        Class.query.filter_by(user_id=current_user.id).order_by(Class.class_name).all()
    )
    teachers = (
        Teacher.query.filter_by(user_id=current_user.id)
        .order_by(Teacher.name, Teacher.surname)
        .all()
    )

    if request.method == "POST":
        try:
            # Veritabanı sorguları ve session işlemleri
            new_assignment = TeacherCourseAssignment(
                course_id=request.form["ders_secimi"],
                teacher_id=request.form["ogretmen_secimi"],
                class_id=request.form["sinif_secimi"],
                user_id=current_user.id,
            )
            db.session.add(new_assignment)
            db.session.commit()
            flash("Ders başarıyla atandı.", "success")

            # Seçili değerleri POST isteği için formdan al
            filter_class = request.form.get("sinif_secimi")
            filter_teacher = request.form.get("ogretmen_secimi")
            filter_course = request.form.get("ders_secimi")

        except IntegrityError as e:
            db.session.rollback()

            flash("Bu ders, öğretmen ve sınıf için zaten atanmış.", "danger")

        # Filtreleri uygula ve sayfayı yeniden yükle
        return redirect(
            url_for(
                "assign_course",
                sinif_secimi=filter_class,
                ogretmen_secimi=filter_teacher,
                ders_secimi=filter_course,
            )
        )

    return render_template(
        "ders_atama.html",
        page_title="Ders Atama",
        courses=courses,
        teachers=teachers,
        classes=classes,
        programlar=programlar,
        filter_class=filter_class,
        filter_teacher=filter_teacher,
        filter_course=filter_course,
    )


# Ders Atama Filtreleme İşlemi
@app.route("/get-filtered-data", methods=["GET"])
@login_required
def get_filtered_data():
    current_user = User.query.filter_by(username=session["username"]).first()

    sinif_secimi = request.args.get("sinif_secimi")
    ogretmen_secimi = request.args.get("ogretmen_secimi")
    ders_secimi = request.args.get("ders_secimi")

    query = (
        db.session.query(TeacherCourseAssignment)
        .join(Course)
        .join(Teacher)
        .join(Class)
        .filter(TeacherCourseAssignment.user_id == current_user.id)
    )

    if sinif_secimi:
        query = query.filter(TeacherCourseAssignment.class_id == sinif_secimi)
    if ogretmen_secimi:
        query = query.filter(TeacherCourseAssignment.teacher_id == ogretmen_secimi)
    if ders_secimi:
        query = query.filter(TeacherCourseAssignment.course_id == ders_secimi)

    # Öğretmen ismine göre sırala
    query = query.order_by(Teacher.name, Teacher.surname)
    programlar = query.all()

    result = []
    for program in programlar:
        result.append(
            {
                "id": program.id,
                "course_name": program.course.course_name,
                "teacher_name": f"{program.teacher.name} {program.teacher.surname}",
                "class_name": program.class_.class_name,
                "weekly_hours": program.course.weekly_hours,
                "distribution_format": program.course.distribution_format,
            }
        )

    return jsonify(result)


# Ders Atama Sil
@app.route("/ders-dagitimi-sil/<int:assignment_id>", methods=["GET"])
@login_required
def delete_assignment(assignment_id):
    current_user = User.query.filter_by(username=session["username"]).first()
    try:
        assignment = TeacherCourseAssignment.query.filter_by(
            id=assignment_id, user_id=current_user.id
        ).first_or_404()

        db.session.delete(assignment)
        db.session.commit()

        flash("Ders atama başarıyla silindi.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Ders ataması silinirken bir hata oluştu: {e}", "danger")

    return redirect(url_for("assign_course"))


# Programlar
@app.route("/schedules")
@login_required
def schedules():
    current_user = User.query.filter_by(id=session["user_id"]).first()
    # Ders programlarını tek bir sorguda alma
    all_schedules = (
        CourseSchedule.query.filter_by(user_id=current_user.id)
        .order_by(
            CourseSchedule.class_id,
            CourseSchedule.teacher_id,
            CourseSchedule.day,
            CourseSchedule.hour,
        )
        .all()
    )

    # Açık saatleri alma
    school_schedule = Schedule.query.filter_by(
        user_id=current_user.id, is_open=True
    ).all()
    open_hours_by_day = create_open_day_hour_set(school_schedule)

    # Yerleştirilemeyen dersleri session'dan alma
    unplaced_assignments = sorted(
        session.get("unplaced_assignments", []), key=lambda x: x["class_id"]
    )

    # Program yapıları
    schedule_by_class = {}
    schedule_by_teacher = {}

    # Programları işleme
    for entry in all_schedules:
        # Sınıf bazlı program
        class_id = entry.class_id
        if class_id not in schedule_by_class:
            schedule_by_class[class_id] = {
                "class_name": entry.class_.class_name,
                "schedule": {day: {} for day in open_hours_by_day},
            }
        schedule_by_class[class_id]["schedule"][entry.day][entry.hour] = {
            "course_id": entry.course_id,
            "course_name": entry.course.course_name,
            "teacher_name": f"{entry.teacher.name} {entry.teacher.surname}",
            "teacher_id": entry.teacher.id,
            "class_name": entry.class_.class_name,
            "block_id": entry.id,
        }

        # Öğretmen bazlı program
        teacher_id = entry.teacher_id
        if teacher_id not in schedule_by_teacher:
            schedule_by_teacher[teacher_id] = {
                "teacher_name": f"{entry.teacher.name} {entry.teacher.surname}",
                "schedule": {day: {} for day in open_hours_by_day},
            }
        schedule_by_teacher[teacher_id]["schedule"][entry.day][entry.hour] = {
            "course_id": entry.course_id,
            "course_name": entry.course.course_name,
            "teacher_name": f"{entry.teacher.name} {entry.teacher.surname}",
            "teacher_id": entry.teacher.id,
            "class_name": entry.class_.class_name,
            "block_id": entry.id,
        }

    return render_template(
        "schedules.html",
        schedule_by_class=schedule_by_class,
        schedule_by_teacher=schedule_by_teacher,
        open_hours_by_day=open_hours_by_day,
        unplaced_assignments=unplaced_assignments,
    )


# Sabitler
HOURS = [i for i in range(1, 11)]
DAYS = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]


def create_open_day_hour_set(schedules):
    open_hours_by_day = {
        day: sorted(
            {entry.hour for entry in schedules if entry.day == day and entry.is_open},
            key=HOURS.index,
        )
        for day in sorted(
            {entry.day for entry in schedules if entry.is_open}, key=DAYS.index
        )
    }
    return open_hours_by_day


def create_teacher_avail(teacher_schedules, open_hours_by_day):
    teacher_avail = {}
    # Tüm öğretmen ID'lerini al
    for teacher_id in {teacher.teacher_id for teacher in teacher_schedules}:
        teacher_avail[teacher_id] = {}
        # Her açık gün için öğretmenin müsaitlik durumunu oluştur
        for day, hours in open_hours_by_day.items():
            teacher_open_hours = {
                entry.hour
                for entry in teacher_schedules
                if entry.teacher_id == teacher_id and entry.day == day and entry.is_open
            }
            teacher_avail[teacher_id][day] = {
                hour: (hour in teacher_open_hours) for hour in hours
            }

    return teacher_avail


def create_class_avail(classes, school_schedules, open_hours_by_day):
    class_avail = {}

    # Her sınıf için işlem yap
    for class_ in classes:
        class_avail[class_.id] = {}

        # Her gün için sınıfın müsaitlik durumu
        for day, hours in open_hours_by_day.items():
            class_open_hours = {
                entry.hour
                for entry in school_schedules
                if entry.day == day and entry.is_open
            }
            class_avail[class_.id][day] = {
                hour: (hour in class_open_hours) for hour in hours
            }

    return class_avail


def load_availability():
    current_user = db.session.get(User, session["user_id"])
    school_schedules = (
        db.session.query(Schedule.day, Schedule.hour, Schedule.is_open)
        .filter_by(user_id=current_user.id, is_open=True)
        .all()
    )
    open_hours_by_day = create_open_day_hour_set(school_schedules)
    teacher_schedules = (
        db.session.query(
            TeacherSchedule.teacher_id,
            TeacherSchedule.day,
            TeacherSchedule.hour,
            TeacherSchedule.is_open,
        )
        .filter(
            TeacherSchedule.user_id == current_user.id,
        )
        .all()
    )
    teacher_avail = create_teacher_avail(teacher_schedules, open_hours_by_day)
    classes = Class.query.filter_by(user_id=current_user.id).all()
    class_avail = create_class_avail(classes, school_schedules, open_hours_by_day)
    school_avail_data = {
        "open_hours_by_day": open_hours_by_day,
    }
    return teacher_avail, class_avail, open_hours_by_day


def update_teacher_avail(teacher_avail, teacher_id, day, hour, is_open):
    """
    Öğretmen sözlüğünü güncellemek için fonksiyon.
    """
    # Öğretmenin sözlükte olup olmadığını kontrol et
    if teacher_id not in teacher_avail:
        teacher_avail[teacher_id] = {}
    # Belirtilen saati ve açık/kapalı durumunu güncelle
    teacher_avail[teacher_id][day][hour] = is_open

    return teacher_avail


def update_class_avail(class_avail, class_id, day, hour, is_open):
    """
    Sınıf sözlüğünü güncellemek için fonksiyon.
    """
    # Sınıfın sözlükte olup olmadığını kontrol et
    if class_id not in class_avail:
        class_avail[class_id] = {}

    # Belirtilen saati ve açık/kapalı durumunu güncelle
    class_avail[class_id][day][hour] = is_open

    return class_avail


def course_block_list_get():
    current_user = User.query.filter_by(username=session["username"]).first()
    if current_user is None:
        flash("Kullanıcı bulunamadı. Lütfen tekrar oturum açın.", "danger")
        return redirect(url_for("login"))

    assignments = TeacherCourseAssignment.query.filter_by(user_id=current_user.id).all()

    if not assignments:
        flash("Ders ataması bulunamadı. Lütfen önce ders ataması yapın.", "warning")
        return redirect(url_for("assign_course"))

    course_ids = [assignment.course_id for assignment in assignments]
    courses = Course.query.filter(Course.id.in_(course_ids)).all()
    course_dict = {course.id: course for course in courses}

    teacher_dict = {}
    teacher_ids = [assignment.teacher_id for assignment in assignments]
    teachers = Teacher.query.filter(Teacher.id.in_(teacher_ids)).all()
    for teacher in teachers:
        teacher_dict[teacher.id] = teacher

    class_dict = {}
    class_ids = [
        assignment.class_id
        for assignment in assignments
        if assignment.class_id is not None
    ]  # if condition ekle
    classes = Class.query.filter(Class.id.in_(class_ids)).all()
    for class_ in classes:
        class_dict[class_.id] = class_

    course_block_list = {}

    block_id_counter = 1  # Ders blokları için sayaç

    for assignment in assignments:
        # Sadece class_id değeri None olmayan kayıtları dikkate al
        if assignment.class_id is not None:
            course = course_dict.get(assignment.course_id)
            teacher = teacher_dict.get(assignment.teacher_id)
            class_ = class_dict.get(assignment.class_id)

            if not course or not teacher or not class_:
                continue

            parts = [int(p) for p in course.distribution_format.split("+") if p]

            for part in parts:
                if assignment.class_id not in course_block_list:
                    course_block_list[assignment.class_id] = []
                course_block_list[assignment.class_id].append(
                    {
                        "block_id": block_id_counter,
                        "course_id": course.id,
                        "course_name": course.course_name,
                        "class_id": assignment.class_id,
                        "class_name": class_.class_name,
                        "teacher_name": f"{teacher.name} {teacher.surname}",
                        "teacher_id": teacher.id,
                        "weekly_hours": part,
                        "placed": False,
                    }
                )
                block_id_counter += 1

    for class_id, courses in course_block_list.items():
        course_block_list[class_id] = sorted(
            courses, key=lambda course: course["weekly_hours"], reverse=True
        )

    return course_block_list


def is_valid_placement(
    schedule,
    block_id,
    class_id,
    teacher_id,
    block_size,
    open_hours_by_day,
    teacher_avail,
    class_avail,
    course_block_list,
    day,
    hour,
):
    """
    Belirtilen dersin, öğretmenin ve sınıfın belirli bir zaman dilimine yerleştirilmesinin geçerli olup olmadığını kontrol eder.
    """

    if any(
        h not in open_hours_by_day.get(day, [])
        or schedule[class_id][day].get(h) is not None
        for h in range(hour, hour + block_size)
    ):
        return False

    if any(
        not class_avail[class_id][day].get(h, False)
        or not teacher_avail[teacher_id][day].get(h, False)
        for h in range(hour, hour + block_size)
    ):
        return False

    if any(
        course_info["block_id"] == block_id and course_info["placed"]
        for course_info in course_block_list[class_id]
    ):
        return False

    if any(
        check_hour in open_hours_by_day.get(day, [])
        and (schedule.get(class_id, {}).get(day, {}).get(check_hour) or {}).get(
            "teacher_id"
        )
        == teacher_id
        for delta in [-1, block_size]
        for check_hour in [hour + delta]
    ):
        return False

    # Aynı öğretmen, aynı gün, aynı sınıfa aynı dersten bir daha yerleşememeli.

    current_course_id = None
    for course_info in course_block_list[class_id]:
        if course_info["block_id"] == block_id:
            current_course_id = course_info["course_id"]
            break
    # Şimdi tüm diğer saatlere bakacağız ve bu course_id yi kontrol edeceğiz.

    for check_hour in range(1, len(open_hours_by_day.get(day, {})) + 1):
        if (
            check_hour in schedule[class_id][day]
            and schedule[class_id][day][check_hour] is not None
        ):
            if (
                schedule[class_id][day][check_hour].get("teacher_id") == teacher_id
                and schedule[class_id][day][check_hour].get("course_id")
                == current_course_id
            ):
                return False
    return True


def assign_course_block(
    schedule,
    block_id,
    course_id,
    course_name,
    class_id,
    class_name,
    teacher_name,
    teacher_id,
    day,
    hour,
    block_size,
    course_block_list,
    teacher_avail,
    class_avail,
):

    for hour in range(hour, hour + block_size):
        if schedule[class_id][day][hour] is None:
            schedule[class_id][day][hour] = {
                "block_id": block_id,
                "course_id": course_id,
                "teacher_id": teacher_id,
                "ders_adi": course_name,
                "ogretmen_adi": teacher_name,
            }
            # Öğretmen ve sınıf müsaitlik durumunu güncelle
            update_teacher_avail(teacher_avail, teacher_id, day, hour, False)
            update_class_avail(class_avail, class_id, day, hour, False)

        else:
            print(f"Uyarı: {class_id} sınıfı için {day} günü {hour}. saat zaten dolu!")
            # Dolu hücreleri de güncelle
            # course_block_list içindeki ilgili dersi bul ve 'placed' değerini güncelle
        for course_info in course_block_list[class_id]:
            if schedule[class_id][day][hour] is not None:
                if course_info["block_id"] == block_id:
                    course_info["placed"] = True
                    break

    return schedule, course_block_list, True


def remove_lesson(schedule, class_id, day, hour):
    if schedule[class_id][day][hour] is not None:
        schedule[class_id][day][hour] = None


def create_unplaced_assignments(course_block_list):
    unplaced_assignments = []
    for class_id, courses in course_block_list.items():
        for course_info in courses:
            if not course_info["placed"]:
                unplaced_assignments.append(
                    {
                        "block_id": course_info["block_id"],
                        "course_id": course_info["course_id"],
                        "teacher_id": course_info["teacher_id"],
                        "class_id": course_info["class_id"],
                        "course_name": course_info["course_name"],
                        "class_name": course_info["class_name"],
                        "teacher_name": course_info["teacher_name"],
                        "weekly_hours": course_info["weekly_hours"],
                        "placed_hours": 0,
                    }
                )
    return unplaced_assignments


def initialize_schedule(classes, open_hours_by_day):
    schedule = {}

    # Her sınıf için takvim oluşturuluyor
    for class_ in classes:
        schedule[class_.id] = {
            day: {hour: None for hour in open_hours_by_day.get(day, [])}
            for day in open_hours_by_day
        }

    return schedule


def calculate_teacher_workload_ratio(teacher_avail, course_block_list):
    """
    Öğretmenlerin doluluk oranlarını hesaplar.
    Args:
        teacher_avail (dict): Öğretmenlerin müsaitlik bilgileri.
        course_list (dict): Ders atama bilgileri (yerleşmemiş dersler dahil).
    Returns:
        dict: Öğretmenlerin doluluk oranlarını içeren bir sözlük.
    """
    teacher_workload_ratio = {}

    teacher_total_available_hours = {}
    teacher_available_days = {}

    for teacher_id, availability in teacher_avail.items():
        total_available_hours = 0
        available_days = 0
        for day, hours in availability.items():
            if any(
                is_available for hour, is_available in hours.items() if is_available
            ):
                total_available_hours += sum(
                    1 for hour, is_available in hours.items() if is_available
                )
                available_days += 1
        teacher_total_available_hours[teacher_id] = total_available_hours
        teacher_available_days[teacher_id] = available_days

    # Her öğretmenin yerleşmemiş derslerini sayalım
    for teacher_id in teacher_avail.keys():
        # Yerleşmemiş ders sayısını hesapla
        total_unplaced_courses = 0
        for class_id, courses in course_block_list.items():
            for course_info in courses:
                if course_info.get("teacher_id") == teacher_id and not course_info.get(
                    "placed", False
                ):
                    total_unplaced_courses += course_info.get("weekly_hours")

        # Hata kontrolü: Yerleşmemiş ders sayısı müsait saatten büyükse
        if total_unplaced_courses > teacher_total_available_hours[teacher_id]:
            raise ValueError(
                f"Öğretmen ID {teacher_id}: Yerleşmemiş ders sayısı ({total_unplaced_courses}) müsait zamanından ({teacher_total_available_hours[teacher_id]}) büyük!"
            )

        # Doluluk oranını hesapla: müsait saat / yerleşmemiş ders sayısı
        if total_unplaced_courses > 0:
            workload_ratio = (
                teacher_total_available_hours[teacher_id]
                / total_unplaced_courses
                * teacher_available_days[teacher_id]
                * teacher_available_days[teacher_id]
            )
        else:
            workload_ratio = 0  # Eğer yerleşmemiş ders yoksa oran sıfır

        # Yerleşmemiş ders sayısı veya müsait saat sıfırsa listeye ekleme
        if total_unplaced_courses > 0 or teacher_total_available_hours[teacher_id] > 0:
            teacher_workload_ratio[teacher_id] = workload_ratio

    # Öğretmenleri doluluk oranına göre sıralıyoruz
    teacher_workload_ratio = dict(
        sorted(teacher_workload_ratio.items(), key=lambda item: item[1])
    )

    return teacher_workload_ratio


def find_difficult_times(teacher_avail, open_hours_by_day):
    """
    Öğretmenlerin müsaitlik bilgilerine göre, en zor zaman dilimlerini belirler.
    En zor zaman dilimleri, en az öğretmenin müsait olduğu saatlerdir.

    Args:
        teacher_avail (dict): Öğretmenlerin müsaitlik bilgisi.
        open_hours_by_day (dict): Günlere göre açık saatler.

    Returns:
        list: En zor zaman dilimlerinin listesi.
    """
    time_load = {}

    # Zor zaman dilimlerini belirlemek için her gün ve saat üzerinde döngü kuruyoruz
    for day, hours in open_hours_by_day.items():
        for hour in hours:
            time_load[(day, hour)] = 0
            # Öğretmenlerin müsaitlik bilgisi üzerinden her saat için yük hesaplama
            for teacher_id in teacher_avail:
                if (
                    day in teacher_avail[teacher_id]
                    and hour in teacher_avail[teacher_id][day]
                ):
                    if teacher_avail[teacher_id][day][hour]:
                        time_load[(day, hour)] += 1

    sorted_time_load = sorted(time_load.items(), key=lambda item: item[1])
    difficult_times = [(day, hour) for (day, hour), load in sorted_time_load]

    return difficult_times


@app.route("/create_schedule_genetic", methods=["POST"])
@login_required
def create_genetic():
    schedule = create_schedule()
    return redirect(url_for("schedules"))


def create_schedule():
    current_user = User.query.filter_by(username=session["username"]).first()
    if current_user is None:
        flash("Kullanıcı bulunamadı. Lütfen tekrar oturum açın.", "danger")
        return redirect(url_for("login"))

    teacher_avail, class_avail, open_hours_by_day = load_availability()
    course_block_list = course_block_list_get()
    schedule = initialize_schedule(
        Class.query.filter_by(user_id=session["user_id"]).all(), open_hours_by_day
    )

    difficult_times = find_difficult_times(teacher_avail, open_hours_by_day)
    teacher_workload_ratios = calculate_teacher_workload_ratio(
        teacher_avail, course_block_list
    )

    unplaced_assignments = create_unplaced_assignments(course_block_list)
    # print(course_block_list)
    placed_in_difficult_time = False
    for day, hour in difficult_times:
        for class_id, _ in schedule.items():
            for assignment in course_block_list[class_id]:
                for teacher_id, ratio in calculate_teacher_workload_ratio(
                    teacher_avail, course_block_list
                ).items():
                    if assignment["teacher_id"] == teacher_id:
                        if is_valid_placement(
                            schedule,
                            assignment["block_id"],
                            class_id,
                            teacher_id,
                            assignment["weekly_hours"],
                            open_hours_by_day,
                            teacher_avail,
                            class_avail,
                            course_block_list,
                            day,
                            hour,
                        ):
                            assign_course_block(
                                schedule,
                                assignment["block_id"],
                                assignment["course_id"],
                                assignment["course_name"],
                                class_id,
                                assignment["class_name"],
                                assignment["teacher_name"],
                                teacher_id,
                                day,
                                hour,
                                assignment["weekly_hours"],
                                course_block_list,
                                teacher_avail,
                                class_avail,
                            )
    unplaced_assignments = create_unplaced_assignments(course_block_list)
    # parametre olarak alınan döngü sayısı
    for _ in range(100):  # 10 defa döngüyü tekrarla
        schedule, course_block_list = try_place_courses(
            schedule,
            unplaced_assignments,
            teacher_avail,
            class_avail,
            open_hours_by_day,
            course_block_list,
        )
    unplaced_assignments = create_unplaced_assignments(course_block_list)

    # Veritabanı işlemleri
    CourseSchedule.query.filter_by(user_id=current_user.id).delete()

    for class_id, days_data in schedule.items():
        for day, hours in days_data.items():
            for hour, lesson_info in hours.items():
                if lesson_info:
                    new_course_schedule = CourseSchedule(
                        day=day,
                        hour=hour,
                        course_id=lesson_info["course_id"],
                        teacher_id=lesson_info["teacher_id"],
                        class_id=class_id,
                        user_id=current_user.id,
                    )
                    db.session.add(new_course_schedule)
    db.session.commit()
    # Yerleşim raporu sonuçlarına göre flash mesajları

    print(
        "unplassssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss"
    )

    session["unplaced_assignments"] = unplaced_assignments
    return schedule


def try_place_courses(
    schedule,
    unplaced_assignments,
    teacher_avail,
    class_avail,
    open_hours_by_day,
    course_block_list,
):
    """Yerleşmeyen dersleri mevcut programa yerleştirmeye çalışır."""

    # yerleşmeyen dersleri gruplara ayır
    unplaced_assignments_by_class = defaultdict(list)
    for assignment in unplaced_assignments:
        unplaced_assignments_by_class[assignment["class_id"]].append(assignment)

    for class_id, assignments in unplaced_assignments_by_class.items():
        for assignment in assignments:
            # 2. Adım: Ders Değiştirerek Yerleştirme (Mevcut derslerle oyna)
            schedule, unplaced_assignments, course_block_list, placed = (
                try_swap_placement(
                    schedule,
                    assignment,
                    teacher_avail,
                    class_avail,
                    open_hours_by_day,
                    course_block_list,
                    unplaced_assignments,
                )
            )
            if placed:
                continue

    return schedule, course_block_list


def try_swap_placement(
    schedule,
    assignment,
    teacher_avail,
    class_avail,
    open_hours_by_day,
    course_block_list,
    unplaced_assignments,
):
    """Mevcut derslerle yer değiştirerek dersi yerleştirmeye çalışır."""
    class_id = assignment["class_id"]
    teacher_id = assignment["teacher_id"]
    block_size = assignment["weekly_hours"]
    block_id = assignment["block_id"]

    day, hour = find_available_slot(
        schedule,
        assignment,
        teacher_avail,
        class_avail,
        open_hours_by_day,
        course_block_list,
    )

    if day is None or hour is None:
        return schedule, unplaced_assignments, course_block_list, False
    else:

        if check_block_conflict(
            schedule,
            class_id,
            teacher_id,
            block_size,
            open_hours_by_day,
            day,
            hour,
            course_block_list,
            block_id,
        ):
            conflicting_blocks = find_conflicting_blocks(
                schedule,
                class_id,
                teacher_id,
                block_size,
                open_hours_by_day,
                day,
                hour,
                course_block_list,
                block_id,
            )
            schedule, unplaced_assignments, course_block_list = (
                remove_and_unplace_blocks(
                    schedule,
                    conflicting_blocks,
                    unplaced_assignments,
                    course_block_list,
                    class_id,
                    day,
                    hour,
                )
            )
            # Çakışma çözüldükten sonra dersi tekrar yerleştirmeyi deniyoruz
            day, hour = find_available_slot(
                schedule,
                assignment,
                teacher_avail,
                class_avail,
                open_hours_by_day,
                course_block_list,
            )
            if day is None or hour is None:
                return schedule, unplaced_assignments, course_block_list, False
            if check_block_conflict(
                schedule,
                class_id,
                teacher_id,
                block_size,
                open_hours_by_day,
                day,
                hour,
                course_block_list,
                block_id,
            ):
                return schedule, unplaced_assignments, course_block_list, False
            else:
                m = True
                # Blok için tüm saatleri kontrol et
                for h in range(hour, hour + block_size):
                    # 3. Öğretmen belirtilen saatte müsait mi?
                    if not teacher_avail[teacher_id][day].get(h, False):
                        m = False

                if m == True:
                    schedule, course_block_list, placed = assign_course_block(
                        schedule,
                        block_id,
                        assignment["course_id"],
                        assignment["course_name"],
                        class_id,
                        assignment["class_name"],
                        assignment["teacher_name"],
                        teacher_id,
                        day,
                        hour,
                        block_size,
                        course_block_list,
                        teacher_avail,
                        class_avail,
                    )
                    print(
                        "Çakışmalı atandı",
                        day,
                        hour,
                        assignment["class_name"],
                        assignment["teacher_name"],
                        assignment["course_name"],
                    )
                    if placed:
                        return schedule, unplaced_assignments, course_block_list, True
        else:
            m = True
            # Blok için tüm saatleri kontrol et
            for h in range(hour, hour + block_size):
                # 3. Öğretmen belirtilen saatte müsait mi?
                if not teacher_avail[teacher_id][day].get(h, False):
                    m = False
            if m == True:
                schedule, course_block_list, placed = assign_course_block(
                    schedule,
                    block_id,
                    assignment["course_id"],
                    assignment["course_name"],
                    class_id,
                    assignment["class_name"],
                    assignment["teacher_name"],
                    teacher_id,
                    day,
                    hour,
                    block_size,
                    course_block_list,
                    teacher_avail,
                    class_avail,
                )
                print(
                    "Çakışmasız atandı",
                    day,
                    hour,
                    assignment["class_name"],
                    assignment["teacher_name"],
                    assignment["course_name"],
                )
                if placed:
                    return schedule, unplaced_assignments, course_block_list, True
    unplaced_assignments = create_unplaced_assignments(course_block_list)
    return schedule, unplaced_assignments, course_block_list, False


def find_available_slot(
    schedule,
    assignment,
    teacher_avail,
    class_avail,
    open_hours_by_day,
    course_block_list,
):
    """Verilen ders bloğu için uygun bir zaman dilimi bulmaya çalışır."""
    class_id = assignment["class_id"]
    teacher_id = assignment["teacher_id"]
    block_size = assignment["weekly_hours"]
    block_id = assignment["block_id"]

    for day in open_hours_by_day:
        for hour_index, hour in enumerate(open_hours_by_day[day]):
            if check_block_availability(
                schedule,
                class_id,
                teacher_id,
                block_size,
                open_hours_by_day,
                teacher_avail,
                class_avail,
                day,
                hour,
            ):
                return day, hour
    return None, None


def check_block_availability(
    schedule,
    class_id,
    teacher_id,
    block_size,
    open_hours_by_day,
    teacher_avail,
    class_avail,
    day,
    hour,
):
    """Belirtilen blok zaman diliminin müsait olup olmadığını kontrol eder."""

    # Blok için tüm saatleri kontrol et
    for h in range(hour, hour + block_size):
        # 1. Saat okulun açık saatleri içinde mi?
        if h not in open_hours_by_day.get(day, []):
            return False

        # 2. Sınıf belirtilen saatte müsait mi?
        if not class_avail[class_id][day].get(h, False):
            return False

        # 3. Öğretmen belirtilen saatte müsait mi?
        if not teacher_avail[teacher_id][day].get(h, False):
            return False, day, hour

    return True


def check_block_conflict(
    schedule,
    class_id,
    teacher_id,
    block_size,
    open_hours_by_day,
    day,
    hour,
    course_block_list,
    block_id,
):
    """
    Belirtilen ders bloğunun olası bir yerleştirme durumunda çakışma yapıp yapmadığını kontrol eder.

    Args:
        schedule (dict): Mevcut ders programı.
        class_id (int): Sınıf ID'si.
        teacher_id (int): Öğretmen ID'si.
        block_size (int): Ders bloğunun boyutu (saat cinsinden).
        open_hours_by_day (dict): Okulun açık olduğu gün ve saatler.
        day (str): Dersin planlandığı gün.
        hour (int): Dersin planlandığı başlangıç saati.
        course_block_list (dict): Tüm ders bloklarının listesi.
        block_id (int): Kontrol edilen bloğun ID'si.

        Returns:
        bool: Çakışma varsa True, yoksa False.
    """
    for h in range(hour, hour + block_size):
        if h not in open_hours_by_day.get(day, []):
            return True
        if schedule[class_id][day].get(h) is not None:
            return True  # Ders varsa çakışma var

    # Öğretmen aynı gün farklı sınıfta aynı saatte derse giremez.
    for check_hour in range(1, len(open_hours_by_day.get(day, {})) + 1):
        if (
            check_hour in schedule[class_id][day]
            and schedule[class_id][day][check_hour] is not None
        ):
            if (
                schedule[class_id][day][check_hour].get("teacher_id") == teacher_id
                and schedule[class_id][day][check_hour].get("block_id") != block_id
            ):
                return True
    return False


def find_conflicting_blocks(
    schedule,
    class_id,
    teacher_id,
    block_size,
    open_hours_by_day,
    day,
    hour,
    course_block_list,
    block_id,
):
    """
    Belirtilen ders bloğunun çakıştığı ders bloklarını tespit eder.
    """
    conflicting_blocks = []

    for h in range(hour, hour + block_size):
        if h not in open_hours_by_day.get(day, []):
            continue
        lesson_info = schedule[class_id][day].get(h)
        if lesson_info and lesson_info.get("block_id") != block_id:
            conflicting_blocks.append(lesson_info)

    # Öğretmen aynı gün farklı sınıfta aynı saatte derse giremez.
    for check_hour in range(1, len(open_hours_by_day.get(day, {})) + 1):
        if (
            check_hour in schedule[class_id][day]
            and schedule[class_id][day][check_hour] is not None
        ):
            if (
                schedule[class_id][day][check_hour].get("teacher_id") == teacher_id
                and schedule[class_id][day][check_hour].get("block_id") != block_id
            ):
                if schedule[class_id][day][check_hour] not in conflicting_blocks:
                    conflicting_blocks.append(schedule[class_id][day][check_hour])

    return conflicting_blocks


def remove_and_unplace_blocks(
    schedule,
    conflicting_blocks,
    unplaced_assignments,
    course_block_list,
    class_id,
    day,
    hour,
):
    """
    Çakışan ders bloklarını programdan kaldırır ve unplaced_assignments listesine ekler.
    """
    print("burada", class_id, hour, day)
    removed_blocks = []
    for conflicting_block in conflicting_blocks:
        if conflicting_block and conflicting_block.get("block_id"):
            block_id = conflicting_block["block_id"]
            for class_id_schedule, days_data in schedule.items():
                for day_schedule, hours in days_data.items():
                    for hour_schedule, lesson_info in hours.items():
                        if lesson_info and lesson_info.get("block_id") == block_id:
                            # Schedule'dan kaldır
                            remove_lesson(
                                schedule, class_id_schedule, day_schedule, hour_schedule
                            )
                            # Unplaced assignment'a ekle
                            for class_id_course, courses in course_block_list.items():
                                for course_info in courses:
                                    if course_info["block_id"] == block_id:
                                        if course_info not in removed_blocks:
                                            unplaced_assignments.append(
                                                {
                                                    "block_id": course_info["block_id"],
                                                    "course_id": course_info[
                                                        "course_id"
                                                    ],
                                                    "teacher_id": course_info[
                                                        "teacher_id"
                                                    ],
                                                    "class_id": course_info["class_id"],
                                                    "course_name": course_info[
                                                        "course_name"
                                                    ],
                                                    "class_name": course_info[
                                                        "class_name"
                                                    ],
                                                    "teacher_name": course_info[
                                                        "teacher_name"
                                                    ],
                                                    "weekly_hours": course_info[
                                                        "weekly_hours"
                                                    ],
                                                    "placed_hours": 0,
                                                }
                                            )
                                            removed_blocks.append(course_info)
    # Programdan çıkarılan yerlerin yerleşmiş statüsünü sıfırla
    for class_id_course, courses in course_block_list.items():
        for course_info in courses:
            for removed_course in removed_blocks:
                if course_info["block_id"] == removed_course["block_id"]:
                    course_info["placed"] = False
    unplaced_assignments = create_unplaced_assignments(course_block_list)
    return schedule, unplaced_assignments, course_block_list


# Giriş Sayfası
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session["username"] = username
            session["user_id"] = user.id
            return redirect(url_for("home"))
        else:
            error = "Geçersiz kullanıcı adı veya şifre!"
            return render_template("login.html", page_title="Giriş Yap", error=error)

    return render_template("login.html", page_title="Giriş Yap")


# Kayıt Sayfası
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        username = request.form["username"]
        password = request.form["password"]

        hashed_password = generate_password_hash(password)

        new_user = User(
            username=username, password=hashed_password, email=email, role="user"
        )
        db.session.add(new_user)
        db.session.commit()

        flash("Kayıt işlemi başarılı!", "success")
        return redirect(url_for("login"))
    return render_template("register.html", page_title="Kayıt Ol")


# Çıkış Yap
@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
