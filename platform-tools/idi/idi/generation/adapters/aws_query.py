"""AWS Query protocol adapter: ARN/ID prefix/PascalCase FK + action mapping."""
import re
from typing import Dict, List, Optional


ACTION_PREFIXES: Dict[str, str] = {
    "Create": "create",
    "Run": "create",
    "Launch": "create",
    "Allocate": "create",
    "Describe": "list",
    "List": "list",
    "Get": "retrieve",
    "Modify": "update",
    "Update": "update",
    "Delete": "delete",
    "Terminate": "delete",
    "Release": "delete",
    "Deregister": "delete",
}

ID_PATTERNS: Dict[str, str] = {
    r"^i-[a-f0-9]+$": "instances",
    r"^vpc-[a-f0-9]+$": "vpcs",
    r"^sg-[a-f0-9]+$": "security-groups",
    r"^subnet-[a-f0-9]+$": "subnets",
    r"^ami-[a-f0-9]+$": "images",
    r"^snap-[a-f0-9]+$": "snapshots",
    r"^vol-[a-f0-9]+$": "volumes",
    r"^igw-[a-f0-9]+$": "internet-gateways",
    r"^nat-[a-f0-9]+$": "nat-gateways",
    r"^rtb-[a-f0-9]+$": "route-tables",
    r"^acl-[a-f0-9]+$": "network-acls",
    r"^eni-[a-f0-9]+$": "network-interfaces",
    r"^eipalloc-[a-f0-9]+$": "addresses",
    r"^lt-[a-f0-9]+$": "launch-templates",
    r"^key-[a-f0-9]+$": "key-pairs",
    r"^placement-group-[a-f0-9]+$": "placement-groups",
}

FIELD_SUFFIX_MAP: Dict[str, str] = {
    "InstanceId": "instances",
    "InstanceIds": "instances",
    "VpcId": "vpcs",
    "VpcIds": "vpcs",
    "SubnetId": "subnets",
    "SubnetIds": "subnets",
    "SecurityGroupId": "security-groups",
    "SecurityGroupIds": "security-groups",
    "GroupId": "security-groups",
    "GroupIds": "security-groups",
    "ImageId": "images",
    "ImageIds": "images",
    "SnapshotId": "snapshots",
    "SnapshotIds": "snapshots",
    "VolumeId": "volumes",
    "VolumeIds": "volumes",
    "InternetGatewayId": "internet-gateways",
    "NatGatewayId": "nat-gateways",
    "RouteTableId": "route-tables",
    "NetworkAclId": "network-acls",
    "NetworkInterfaceId": "network-interfaces",
    "AllocationId": "addresses",
    "LaunchTemplateId": "launch-templates",
    "KeyName": "key-pairs",
    "PlacementGroupName": "placement-groups",
}

ARN_PATTERNS: Dict[str, str] = {
    r"^arn:aws:iam::": "iam",
    r"^arn:aws:ec2:": "ec2",
    r"^arn:aws:s3:": "s3",
    r"^arn:aws:lambda:": "lambda",
    r"^arn:aws:sns:": "sns",
    r"^arn:aws:sqs:": "sqs",
    r"^arn:aws:dynamodb:": "dynamodb",
    r"^arn:aws:rds:": "rds",
    r"^arn:aws:elasticloadbalancing:": "elb",
    r"^arn:aws:kms:": "kms",
}


class AwsQueryAdapter:
    """Adapter for AWS Query protocol APIs."""

    def __init__(self, service: str, known_resources: Optional[set] = None):
        self.service = service
        self.known_resources = known_resources or set()

    def extract_field_refs(self, schema: Dict, source_resource: str) -> List[Dict]:
        """AWS-specific FK detection: ARN, ID prefix, PascalCase suffix."""
        properties = schema.get("properties", {})
        if not properties:
            return []

        refs = []
        for field_name, field_info in properties.items():
            ftype = "array" if field_info.get("type") == "array" else "string"
            pattern = field_info.get("pattern", "")

            arn_service = self._detect_arn_service(pattern)
            if arn_service:
                refs.append({"field": field_name, "target_resource": arn_service,
                             "type": ftype, "source": "arn", "confidence": "high"})
                continue

            target = self._detect_id_pattern(pattern)
            if target and target != source_resource:
                refs.append({"field": field_name, "target_resource": target,
                             "type": ftype, "source": "pattern", "confidence": "high"})
                continue

            target = self._detect_field_suffix(field_name)
            if target and target != source_resource:
                refs.append({"field": field_name, "target_resource": target,
                             "type": ftype, "source": "name", "confidence": "medium"})

        return refs

    def _detect_arn_service(self, pattern: str) -> Optional[str]:
        """Detect AWS service from ARN pattern."""
        if not pattern:
            return None
        for arn_pattern, service in ARN_PATTERNS.items():
            if arn_pattern in pattern:
                return service
        return None

    def _detect_id_pattern(self, pattern: str) -> Optional[str]:
        """Detect resource type from ID pattern."""
        if not pattern:
            return None
        for id_pattern, resource in ID_PATTERNS.items():
            if re.match(id_pattern.replace("$", ""), pattern.lstrip("^")):
                return resource
            if id_pattern.split("-")[0].lstrip("^") in pattern:
                return resource
        return None

    def _detect_field_suffix(self, field_name: str) -> Optional[str]:
        """Detect resource type from PascalCase field name suffix."""
        if field_name in FIELD_SUFFIX_MAP:
            return FIELD_SUFFIX_MAP[field_name]
        for suffix, resource in FIELD_SUFFIX_MAP.items():
            if field_name.endswith(suffix):
                return resource
        return None

    def action_to_operation(self, action: str) -> Optional[str]:
        """Map AWS action name to standard CRUD operation."""
        for prefix, operation in ACTION_PREFIXES.items():
            if action.startswith(prefix):
                return operation
        return None

    def action_to_resource(self, action: str) -> Optional[str]:
        """Extract resource name from AWS action in kebab-case."""
        for prefix in ACTION_PREFIXES:
            if action.startswith(prefix):
                resource_part = action[len(prefix):]
                break
        else:
            return None

        words = re.findall(r'[A-Z][a-z]*', resource_part)
        if not words:
            return None

        resource = "-".join(word.lower() for word in words)
        if not resource.endswith("s"):
            resource += "s"

        return resource
