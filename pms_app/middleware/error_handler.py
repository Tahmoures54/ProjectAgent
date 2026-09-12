from flask import render_template, jsonify, request


class ErrorHandler:
    def __init__(self, app=None):
        if app:
            self.init_app(app)

    def init_app(self, app):
        @app.errorhandler(403)
        def forbidden(e):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Forbidden"}), 403
            return render_template("errors/403.html"), 403

        @app.errorhandler(404)
        def not_found(e):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Resource not found"}), 404
            return render_template("errors/404.html"), 404

        @app.errorhandler(500)
        def server_error(e):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Internal server error"}), 500
            return render_template("errors/500.html"), 500
