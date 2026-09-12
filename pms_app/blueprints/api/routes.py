from flask import jsonify
from pms_app.blueprints.api import api_bp

@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "project-agent-api", "version": "1.0.0"})
