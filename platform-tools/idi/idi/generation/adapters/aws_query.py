"""AWS Query protocol schema adapter.

Handles AWS API conventions:
- PascalCase field names (InstanceId, VpcId, etc.)
- ARN references for cross-service links
- Action-based operation names (CreateInstance, DescribeVpcs)
- Resource ID patterns (i-xxx, vpc-xxx, sg-xxx)
"""
import re
from typing import Dict, List, Optional, Tuple


# Maps AWS action prefixes to standard CRUD operations
ACTION_PREFIXES: Dict[str, str] = {
    "Create": "create",
    "Run": "create",      # RunInstances = create
    "Launch": "create",   # LaunchTemplate
    "Allocate": "create", # AllocateAddress
    "Describe": "list",
    "List": "list",
    "Get": "retrieve",
    "Modify": "update",
    "Update": "update",
    "Delete": "delete",
    "Terminate": "delete",  # TerminateInstances
    "Release": "delete",    # ReleaseAddress
    "Deregister": "delete", # DeregisterImage
}

# Maps ID prefix patterns to resource names
# Pattern -> resource name
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

# Maps field name suffixes to resource names (for fields without patterns)
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

# ARN service patterns
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
    """Adapter for AWS Query protocol APIs.

    Handles PascalCase field names, ARN references, and action-based operations.
    """

    def __init__(self, service: str, known_resources: Optional[set] = None):
        """Initialize adapter for a specific AWS service.

        Args:
            service: AWS service name (ec2, iam, s3, etc.)
            known_resources: Optional set of known resource names for FK resolution
        """
        self.service = service
        self.known_resources = known_resources or set()

    def extract_field_refs(self, schema: Dict, source_resource: str) -> List[Dict]:
        """Extract foreign key references from a schema.

        Detects FK patterns:
        1. Field name matches known ID suffix (InstanceId -> instances)
        2. Field has pattern matching ID prefix (^i-xxx$ -> instances)
        3. Field has ARN pattern (arn:aws:iam:: -> iam service)

        Args:
            schema: Schema dict with properties
            source_resource: Resource name to exclude self-references

        Returns:
            List of ref dicts: {field, target_resource, type, source, confidence}
        """
        properties = schema.get("properties", {})
        if not properties:
            return []

        refs = []

        for field_name, field_info in properties.items():
            ref = self._detect_field_ref(field_name, field_info, source_resource)
            if ref:
                refs.append(ref)

        return refs

    def _detect_field_ref(self, field_name: str, field_info: Dict,
                          source_resource: str) -> Optional[Dict]:
        """Detect if a field is a foreign key reference.

        Args:
            field_name: Name of the field (PascalCase)
            field_info: Field schema info
            source_resource: Resource to exclude self-refs

        Returns:
            Ref dict or None
        """
        field_type = field_info.get("type", "string")
        pattern = field_info.get("pattern", "")
        is_array = field_type == "array"

        # Check for ARN pattern first
        arn_service = self._detect_arn_service(pattern)
        if arn_service:
            return {
                "field": field_name,
                "target_resource": arn_service,
                "type": "array" if is_array else "string",
                "source": "arn",
                "confidence": "high",
            }

        # Check ID pattern in schema
        target = self._detect_id_pattern(pattern)
        if target and target != source_resource:
            return {
                "field": field_name,
                "target_resource": target,
                "type": "array" if is_array else "string",
                "source": "pattern",
                "confidence": "high",
            }

        # Check field name suffix
        target = self._detect_field_suffix(field_name)
        if target and target != source_resource:
            return {
                "field": field_name,
                "target_resource": target,
                "type": "array" if is_array else "string",
                "source": "name",
                "confidence": "medium",
            }

        return None

    def _detect_arn_service(self, pattern: str) -> Optional[str]:
        """Detect AWS service from ARN pattern.

        Args:
            pattern: Regex pattern from schema

        Returns:
            Service name or None
        """
        if not pattern:
            return None

        for arn_pattern, service in ARN_PATTERNS.items():
            if arn_pattern in pattern:
                return service

        return None

    def _detect_id_pattern(self, pattern: str) -> Optional[str]:
        """Detect resource type from ID pattern.

        Args:
            pattern: Regex pattern from schema

        Returns:
            Resource name or None
        """
        if not pattern:
            return None

        for id_pattern, resource in ID_PATTERNS.items():
            # Check if the pattern matches the ID prefix pattern
            if re.match(id_pattern.replace("$", ""), pattern.lstrip("^")):
                return resource
            # Also check if the schema pattern contains our expected prefix
            if id_pattern.split("-")[0].lstrip("^") in pattern:
                return resource

        return None

    def _detect_field_suffix(self, field_name: str) -> Optional[str]:
        """Detect resource type from field name suffix.

        Args:
            field_name: PascalCase field name

        Returns:
            Resource name or None
        """
        # Direct match
        if field_name in FIELD_SUFFIX_MAP:
            return FIELD_SUFFIX_MAP[field_name]

        # Check if field ends with a known suffix
        for suffix, resource in FIELD_SUFFIX_MAP.items():
            if field_name.endswith(suffix):
                return resource

        return None

    def extract_outputs(self, schema: Dict, path_prefix: str = "") -> List[Dict]:
        """Extract output fields from a response schema.

        Flattens nested structures to produce a list of output fields.

        Args:
            schema: Response schema dict
            path_prefix: Prefix for nested field paths

        Returns:
            List of output dicts: {field, type, path}
        """
        outputs = []
        properties = schema.get("properties", {})

        for field_name, field_info in properties.items():
            field_type = field_info.get("type", "string")
            current_path = f"{path_prefix}.{field_name}" if path_prefix else field_name

            if field_type == "array":
                items = field_info.get("items", {})
                if items.get("type") == "object":
                    # Recurse into array items
                    nested_outputs = self.extract_outputs(items, f"{current_path}[]")
                    outputs.extend(nested_outputs)
                else:
                    outputs.append({
                        "field": current_path,
                        "type": f"array[{items.get('type', 'string')}]",
                        "path": current_path,
                    })
            elif field_type == "object":
                # Recurse into nested object
                nested_outputs = self.extract_outputs(field_info, current_path)
                outputs.extend(nested_outputs)
            else:
                outputs.append({
                    "field": field_name,
                    "type": field_type,
                    "path": current_path,
                })

        return outputs

    def action_to_operation(self, action: str) -> Optional[str]:
        """Map AWS action name to standard CRUD operation.

        Args:
            action: AWS action name (e.g., CreateInstance, DescribeVpcs)

        Returns:
            Operation name (create, list, retrieve, update, delete) or None
        """
        for prefix, operation in ACTION_PREFIXES.items():
            if action.startswith(prefix):
                return operation
        return None

    def action_to_resource(self, action: str) -> Optional[str]:
        """Extract resource name from AWS action.

        Args:
            action: AWS action name (e.g., RunInstances, CreateSecurityGroup)

        Returns:
            Resource name in kebab-case or None
        """
        # Remove action prefix to get resource
        for prefix in ACTION_PREFIXES:
            if action.startswith(prefix):
                resource_part = action[len(prefix):]
                break
        else:
            return None

        # Convert PascalCase to kebab-case
        # SecurityGroup -> security-group
        # Instances -> instances
        words = re.findall(r'[A-Z][a-z]*', resource_part)
        if not words:
            return None

        resource = "-".join(word.lower() for word in words)

        # Normalize: security-group -> security-groups (singular to plural)
        # But instances stays instances
        if not resource.endswith("s"):
            resource += "s"

        return resource
