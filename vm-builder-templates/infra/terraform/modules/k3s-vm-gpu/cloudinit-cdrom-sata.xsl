<?xml version="1.0" ?>
<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output omit-xml-declaration="yes" indent="yes"/>
  <xsl:template match="node()|@*">
     <xsl:copy>
       <xsl:apply-templates select="node()|@*"/>
     </xsl:copy>
  </xsl:template>

  <!-- Change cloud-init CDROM from IDE to SATA for UEFI/OVMF compatibility -->
  <!-- Q35/UEFI machines don't properly detect IDE bus, causing cloud-init to not run -->
  <xsl:template match="/domain/devices/disk[@device='cdrom']/target/@bus">
    <xsl:attribute name="bus">
      <xsl:value-of select="'sata'"/>
    </xsl:attribute>
  </xsl:template>

  <!-- Update target dev to use sd* naming for SCSI -->
  <xsl:template match="/domain/devices/disk[@device='cdrom']/target/@dev">
    <xsl:attribute name="dev">
      <xsl:value-of select="'sda'"/>
    </xsl:attribute>
  </xsl:template>

</xsl:stylesheet>
