# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

from flask import Blueprint, abort
from flask_babel import gettext as _
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from .cw_login import current_user

from . import calibre_db, config, db, logger, ub
from .render_template import render_title_template
from .usermanagement import user_login_required
from . import constants

log = logger.create()

reading_progress = Blueprint('reading_progress', __name__)


@reading_progress.route("/readingprogress")
@user_login_required
def reading_progress_page():
    if not config.config_reading_progress or not current_user.check_visibility(constants.SIDEBAR_READING_PROGRESS):
        abort(404)

    KRS2 = aliased(ub.KoboReadingState)
    KB2 = aliased(ub.KoboBookmark)
    max_complete_subq = (
        ub.session.query(func.max(KB2.last_modified))
        .join(KRS2, KB2.kobo_reading_state_id == KRS2.id)
        .filter(KRS2.user_id == ub.KoboReadingState.user_id)
        .filter(KB2.progress_percent >= 100)
        .correlate(ub.KoboReadingState)
        .scalar_subquery()
    )

    query = (
        ub.session.query(ub.KoboReadingState, ub.KoboBookmark, ub.KoboStatistics, ub.User)
        .join(ub.KoboBookmark, ub.KoboBookmark.kobo_reading_state_id == ub.KoboReadingState.id)
        .join(ub.KoboStatistics, ub.KoboStatistics.kobo_reading_state_id == ub.KoboReadingState.id)
        .join(ub.User, ub.User.id == ub.KoboReadingState.user_id)
        .filter(ub.KoboBookmark.progress_percent.isnot(None))
        .filter(ub.KoboBookmark.progress_percent != 0)
        .filter(or_(
            ub.KoboBookmark.progress_percent < 100,
            ub.KoboBookmark.last_modified == max_complete_subq
        ))
    )

    if not current_user.role_all_reading_progress():
        query = query.filter(ub.KoboReadingState.user_id == current_user.id)

    results = query.order_by(ub.KoboBookmark.last_modified.desc()).all()

    book_ids = list({row[0].book_id for row in results})

    books_dict = {}
    if book_ids:
        books = calibre_db.session.query(db.Books).filter(db.Books.id.in_(book_ids)).all()
        books_dict = {b.id: b for b in books}

    page_counts = {}
    if config.config_reading_progress_column and book_ids:
        try:
            cc_class = db.cc_classes[config.config_reading_progress_column]
            cc_values = calibre_db.session.query(cc_class).filter(cc_class.book.in_(book_ids)).all()
            page_counts = {cv.book: cv.value for cv in cc_values}
        except (KeyError, AttributeError, IndexError):
            log.error("Custom Column No.{} does not exist in calibre database".format(
                config.config_reading_progress_column))

    entries = []
    for reading_state, bookmark, statistics, user in results:
        book_id = reading_state.book_id
        book = books_dict.get(book_id)
        title = book.title if book else str(book_id)
        progress = bookmark.progress_percent
        minutes = statistics.spent_reading_minutes or 0

        wpm = None
        if config.config_reading_progress_column:
            word_count = page_counts.get(book_id)
            if word_count and minutes > 0:
                wpm = (word_count * progress / 100.0) / minutes

        entries.append({
            'title': title,
            'book_id': book_id,
            'user': user.name,
            'progress': progress,
            'last_modified': bookmark.last_modified,
            'spent_minutes': minutes,
            'wpm': wpm,
        })

    return render_title_template(
        'reading_progress.html',
        entries=entries,
        has_wpm=bool(config.config_reading_progress_column),
        title=_('Reading Progress'),
        page="reading_progress"
    )
